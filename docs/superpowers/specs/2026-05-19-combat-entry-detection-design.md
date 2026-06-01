# 战斗进入/脱出判定 + Enemy 管理

日期：2026-05-19
状态：设计完成
范围：`src/game/enemy_manager.py`（新建）、`src/scenario_core.py`（修改）、`src/game/agents/keeper.py`（修改）、`src/game/messages.py`（修改）、`src/prompts.py`（修改）、`src/game_loop.py`（修改）、`data/library/core/enemies.json`（修改）

## 动机

当前 `@spawn_enemy(...)` side effect 被正确解析为 `SpawnEnemy` dataclass，但 `apply_side_effects()` 只追加一行 `"[生成敌人] 深潜者 x1 在 车厢1"` 字符串，不产生任何机械效果。`ScenarioWorld` 没有 enemy 追踪字段，没有 combat state，`Investigator.combat_check()` / `damage_roll()` 直接 `raise NotImplementedError`。

目标：让 enemy spawning 真正实例化敌人对象，新增 LLM 驱动的进入战斗判定 + 对峙阶段（可避免战斗），战斗系统本身保持可插拔。

## 架构总览

三层职责分离：

```
SpawnEnemy (side effect)     — 只管触发生成，不持有状态
        ↓
EnemyManager (追踪层)        — 纯状态管理：位置、状态机、条件查询
        ↓
CombatEntryCheck (判定层)    — Keeper 管线内，与 enrich 并行
```

- **EnemyManager** 在 `ScenarioWorld` 上持有一份，追踪所有已生成 enemy 实例。它是战斗系统的数据源——战斗系统从中读取敌人数据，打完回调 `exit_combat()`。
- **CombatEntryCheck** 是 Keeper 流程中的轻量 LLM 调用。确定性闸门先过滤，有候选敌人才调 LLM。
- **对峙阶段** 仅在涉及 `[avoidable]` 敌人时触发，给玩家一次性非战斗解决机会。

## EnemyInstance

```python
@dataclass
class EnemyInstance:
    instance_id: str          # "{enemy_ref}_{uuid8}"
    enemy_ref: str            # 对应 LibraryEnemy.name
    scene: str                # 所属场景
    quantity: int = 1
    status: str = "neutral"   # neutral | hostile | dead

    # 从 LibraryEnemy 带入的结构化 flag
    flags: list[str]          # ["adjacent_aware"] / ["avoidable"] / []
    # 保留自然语言给 LLM 判定用
    combat_behavior: str = ""
```

**状态机**：
- `neutral` — 默认，尚未触发敌意
- `hostile` — 处于交战或即将交战
- `dead` — 已击败/消失

## EnemyManager

所属：`ScenarioWorld.enemy_manager`（与 `memory`、`npc_states` 同级）

```python
class EnemyManager:
    def __init__(self, enemy_library: EnemyLibrary): ...

    # 生命周期
    def spawn(enemy_ref, scene, quantity=1) -> EnemyInstance
    def remove(instance_id)

    # 查询（确定性闸门用）
    def get_active_in_scene(scene: str) -> list[EnemyInstance]
    def get_active_in_range(scene: str, graph) -> list[EnemyInstance]

    # 按种类分组（同场景同 enemy_ref 合并，不同 enemy_ref 独立）
    def group_by_ref(scene: str) -> dict[str, list[EnemyInstance]]

    # 状态机
    def set_status(instance_id, status)
    def mark_dead(instance_id)

    # 战斗系统回调
    def enter_combat(instance_ids: list[str])
    def exit_combat(result)

    # 给 LLM 判定用（格式化敌人上下文文本）
    def get_combat_context(scene, graph) -> str | None

    # 序列化（未来存档用）
    def to_dict() -> dict
    def from_dict(data: dict) -> EnemyManager
```

## Flag

两个 flag，直接嵌入 `combat_behavior` 文本前缀：

```json
{
  "name": "大嘴吞噬者",
  "combat_behavior": "[adjacent_aware] | 不参与常规战斗。它是环境威胁而非可战斗敌人。以固定节奏从后方逼近。"
}
```

```json
{
  "name": "深潜者",
  "combat_behavior": "[avoidable] | 偏好伏击，从水中或暗处突袭。受伤后会撤退到水中。"
}
```

| Flag | 作用 |
|------|------|
| `adjacent_aware` | 确定性闸门检测范围扩展到相邻场景 |
| `avoidable` | 进入战斗前触发对峙阶段，玩家有一次非战斗解决机会 |

大多数敌人不需要 flag，`combat_behavior` 保持纯自然语言。

**解析**：`EnemyLibrary.from_dict()` 在加载时从 `combat_behavior` 字符串中提取 `[flag]` 标记，存入 `LibraryEnemy.flags: list[str]`，同时清理后的自然语言文本存入 `LibraryEnemy.combat_behavior_clean: str`。`EnemyInstance` 创建时从 `LibraryEnemy` 拷贝 flags 和 cleaned text。

## 进入判定：确定性闸门

在 Keeper `process_turn()` 中，Judge 完成后、Enrich 启动前：

```
combat 已激活? → 跳过
        ↓ N
candidates = enemy_manager.get_active_in_range(current_scene, graph)
  - current_scene 中 status != dead 的所有 enemy
  - + 有 [adjacent_aware] flag 的 enemy 所属场景的相邻场景
        ↓
candidates 为空? → 跳过
        ↓ N
启动 combat_entry_detect (LLM, flash, 与 enrich 并行)
```

`get_active_in_range` 中的"相邻场景" = graph 中从该 enemy 所属场景出发，有一条边能直达的其他场景。

## 进入判定：LLM Call

**Prompt 输入**：

```
系统: COC 7th KP 助理。根据玩家行为、本轮结果和场景内敌人的习性，
      判断是否进入回合制战斗。

玩家输入: {raw_text}
本轮结果: {outcomes_summary}
当前位置: {current_scene}

场景内敌人:
- [深潜者] x1 | neutral | [avoidable]
  习性: 偏好伏击，从水中或暗处突袭。受伤后会撤退到水中。
  描述: 克苏鲁神话经典两栖人形生物

- [疯狂信徒] x2 | hostile
  习性: 狂热的邪教徒，以数量优势压倒对手。
  描述: 狂热的邪教徒，不受恐惧影响，战至死不退
```

**`outcomes_summary` 构造**：拼接 `all_outcomes` 中所有 message（按 entity_type 分组：AT / interaction / event / move / search / other）。

**LLM 输出**：

```json
{
  "enter_combat": true,
  "enemy_instance_ids": ["深潜者_a1b2c3d4"],
  "reasoning": "玩家靠近水边并发出声响，触发了深潜者的伏击"
}
```

**判据**：LLM 根据每个敌人的 `combat_behavior` 自然语言 + 玩家本轮行动 + 结果，判断是否有敌人应该进入战斗。

**调用参数**：`deepseek-v4-flash`，`json_mode=True`，`reasoning_effort="low"`。

## 对峙阶段

触发条件：`enter_combat=true` 且至少一个涉及 enemy 带 `[avoidable]` flag。

### 分组

`EnemyManager.group_by_ref(scene)` 按 `enemy_ref` 分组，同场景同种敌人一次检定覆盖全部数量，不同种敌人分开处理。

### 流程

```
Keeper 向玩家展示提示:
  "你还有最后一次机会避免与 [深潜者] 的战斗——你要怎么做？"

玩家输入（自然语言）
        ↓
语义匹配 LLM (flash, 极轻量, json_mode)
  输入: 玩家输入 + 可用的 COC 7th 技能列表
  输出: {matched: true/false, skill_name: "潜行", reason: "..."}
        ↓
   ┌── matched=false → 默认失败 → 进入战斗
   │
   ├── matched=true → D100 技能检定
   │     ├── 成功 → enemy → neutral, 不进入战斗
   │     └── 失败 → 进入战斗
   │
   └── 检定后调用 evaluate_trait_enhancement()
         (同现有 search 路径，支持特殊背景/神话物品修正)
```

### 检定方式与效果

| 检定方式 | 成功 | 失败 |
|----------|------|------|
| 潜行 | 绕过，enemy 保持 hostile 但不进入战斗 | 被发现，进入战斗 |
| 魅惑/取悦 | enemy → neutral | 激怒，进入战斗 |
| 话术/说服 | enemy → neutral | 被识破，进入战斗 |
| 恐吓 | enemy → neutral（退缩） | 激怒，进入战斗 |

**注意**：潜行成功 enemy 保持 hostile（只是绕过），交流/魅力成功 enemy 转 neutral。neutral 下除非主动攻击不会进入战斗。

### 多个 avoidable 敌人

按 enemy_ref 分组逐个处理。每类敌人一次独立匹配 + 检定。处理完一类再下一类。剩余 hostile 敌人进入战斗。

### 玩家"什么都不做"或"直接攻击"

语义匹配返回 `matched=false` → 进入战斗。

## 完整战斗进入数据流

```
process_turn()
  ├── Step 1: parse (LLM, flash)
  ├── Step 2: judge (deterministic)
  │     ├── entity.side_effects → @spawn_enemy(...)
  │     │     └── apply_side_effects()
  │     │           └── world.enemy_manager.spawn("深潜者", "车厢1", 1)
  │     │                 └── EnemyInstance 存入 manager._instances
  │     └── 产出 all_outcomes
  │
  ├── Step 3: [enrich (LLM, flash) ∥ combat_entry_detect]
  │     │
  │     ├── 确定性闸门:
  │     │   ├── combat 已激活? → 跳过
  │     │   ├── candidates = enemy_manager.get_active_in_range(current_scene, graph)
  │     │   └── candidates 为空? → 跳过, combat_check = None
  │     │
  │     └── combat_entry_detect:
  │           输入: raw_text + outcomes_summary + candidates(名/数/状态/combat_behavior)
  │           输出: CombatEntryCheck {enter_combat, enemy_instance_ids, reasoning}
  │
  ├── Step 4: 对峙阶段 (enter_combat=true 且有 avoidable 敌人)
  │     │
  │     ├── per enemy_ref (同场景分组):
  │     │   ├── 提示玩家: "你还有最后一次机会避免与 [X] 的战斗"
  │     │   ├── 玩家输入 → 语义匹配 LLM (flash, 极轻量)
  │     │   │     ├── matched + skill → D100 检定
  │     │   │     │     ├── 成功 → neutral(交流)/保持 hostile but 绕过(潜行)
  │     │   │     │     └── 失败 → 进入战斗
  │     │   │     └── matched=false → 进入战斗
  │     │   └── 检定后 evaluate_trait_enhancement()
  │     │
  │     └── 无 avoidable 敌人 → 直接进入战斗
  │
  ├── Step 5: curate → NarratorBrief
  │
  └── 返回 {brief, combat_pending: CombatInit | None}
        └── game loop 消费 CombatInit → 调用可插拔战斗系统
```

## 并行时序

```
parse ─── judge(确定,快) ─── ┌─ enrich(LLM, flash) ────────┐ ─ 等待 ─ [对峙(可选)] ─ curate
                               │                             │
                               └─ combat_entry_detect(LLM) ─┘
                                  (同 enrich 并行)
```

Combat entry detect 和 enrich 使用同一个 `ThreadPoolExecutor` 或者独立 executor 并行。两者不共享数据，无依赖。对峙阶段在所有 LLM 返回后才可能触发（串行，因为需要玩家输入）。

## 脱出战斗

战斗系统（可插拔，未来实现）返回 `CombatResult {outcome: "win"|"loss"|"flee", defeated_instance_ids: [...], narrative: "..."}`。

```python
EnemyManager.exit_combat(result):
    for instance_id in result.defeated_instance_ids:
        instance.status = "dead"
    # 剩余 enemy: engaged → 恢复原状态（如果之前是 hostile 则保持 hostile）
    for instance_id in self._combat_enemies:
        if instance_id not in result.defeated_instance_ids:
            instance = self._instances[instance_id]
            if instance.status == "engaged":
                instance.status = "hostile"
    self._combat_active = False
    self._combat_enemies.clear()
```

脱出后：
- 场景中仍有 hostile 敌人 → 下回合确定性闸门重新触发 combat entry 判定
- 全部 neutral/dead → 恢复正常叙事循环
- flee 后 enemy 保持 hostile → 玩家可以移动到其他场景避开

## CombatInit（传给可插拔战斗系统）

```python
@dataclass
class CombatInit:
    enemies: list[EnemyInstance]          # 参与战斗的 enemy 实例
    player: Investigator
    initiative_context: str = ""           # combat entry LLM 的 reasoning
    scene: str = ""
```

## 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/game/enemy_manager.py` | 新建 | EnemyInstance + EnemyManager |
| `src/game/messages.py` | 修改 | 新增 CombatEntryCheck, CombatInit, StandoffPrompt |
| `src/prompts.py` | 修改 | 新增 build_combat_entry_prompt, build_standoff_match_prompt |
| `src/scenario_core.py` | 修改 | ScenarioWorld 新增 enemy_manager 字段；apply_side_effects 调用 EnemyManager.spawn |
| `src/game/agents/keeper.py` | 修改 | process_turn 新增 combat_entry_detect + 对峙阶段 |
| `src/game_loop.py` | 修改 | init_game 加载 EnemyLibrary 传入 ScenarioWorld；删除重复的 _apply_side_effects |
| `src/library/enemies.py` | 修改 | LibraryEnemy 新增 flags + combat_behavior_clean；from_dict 解析 [flag] |
| `data/library/core/enemies.json` | 修改 | 给 深潜者 加 `[avoidable]`，给 大嘴吞噬者 加 `[adjacent_aware]` |
| `src/game/__init__.py` | 修改 | 导出新类型 |
