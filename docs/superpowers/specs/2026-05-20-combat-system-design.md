# Combat System — 战斗机制设计

日期：2026-05-20
状态：设计阶段
前置：`docs/superpowers/specs/2026-05-19-combat-entry-detection-design.md`（进入/脱出判定）
范围：`src/game/combat.py`（新建）、`src/investigator/models.py`（修改）、`src/game_loop.py`（修改）

## 动机

战斗进入/脱出判定和 Enemy 管理由 `2026-05-19-combat-entry-detection-design` 覆盖。本设计聚焦战斗循环本身：回合结构、动作系统、伤害计算、敌人 AI、叙事输出。

核心原则：简化 COC 7th 规则（B 方案），玩家动作固定选项（零 LLM），敌人规则驱动，每轮 LLM 生成叙事。保留 trait enhancement 接口。

## 架构

```
CombatSystem (独立回合控制器, 不经过 Keeper 流水线)
  │
  ├── 初始化: 先攻排序 (DEX)、收集敌人、加载玩家武器
  │
  ├── 每轮:
  │     ├── 展示战况 (机械文本)
  │     ├── 玩家选择动作 (固定选项)
  │     ├── 动作执行 (技能检定 + trait enhancement + 伤害计算)
  │     ├── 敌人行动 (按 attack.weight 选攻击 → 目标选择 → 检定)
  │     ├── 死亡检查 (玩家0 → 失败; 敌全灭 → 胜利)
  │     └── 叙事生成 (LLM, flash, json_mode → narrative + scene_hint)
  │
  └── 返回 CombatResult → game_loop 恢复正常回合
```

## 数据结构

```python
@dataclass
class CombatState:
    round: int = 1
    enemies: list[EnemyInstance] = field(default_factory=list)
    player_hp: int = 0
    player_hp_max: int = 0
    player_san: int = 0
    initiative_order: list[str] = field(default_factory=list)  # "player" | enemy instance_id
    current_actor_idx: int = 0
    is_player_turn: bool = True
    finished: bool = False
    log: list[CombatAction] = field(default_factory=list)  # 本轮所有行动的机械记录


@dataclass
class CombatAction:
    actor: str                  # "player" | enemy instance_id
    action_type: str            # "attack" | "dodge" | "flee" | "special"
    weapon: str = ""            # 武器名或攻击名
    skill_name: str = ""        # 使用的技能名
    skill_value: int = 0
    roll: int = 0               # D100 结果
    tier: str = ""              # 检定等级
    target: str = ""            # 目标 actor
    damage: str = ""            # 伤害公式或实际伤害
    hp_before: int = 0
    hp_after: int = 0
    narrative: str = ""
    success: bool = False


@dataclass
class CombatResult:
    outcome: str                # "win" | "loss" | "flee"
    defeated_instance_ids: list[str]
    narrative: str
    player_hp: int
    player_san: int
    rounds: int
```

## 先攻与回合流

DEX 降序排列所有参与者（玩家 + 所有敌人）。同一 DEX 随机排序。

```
DEX 80 玩家     ← 先动
DEX 75 深潜者A
DEX 50 深潜者B
DEX 30 深潜者C
```

每轮按此顺序执行。玩家行动时等待输入，敌人行动自动执行。

## 玩家动作

固定选项列表，基于当前状态动态生成：

| 动作 | 技能 | 检定 D100 vs | 成功效果 |
|------|------|-------------|----------|
| 拳击 | 格斗(拳) | 格斗值 | 1D3+DB 伤害 |
| 踢击 | 格斗(脚) | 格斗值 | 1D6+DB 伤害 |
| 手持武器 | 对应技能 | 技能值 | 武器伤害+DB |
| 回避 | 回避 | 回避值 | 本轮首个对玩家的攻击自动失败 |
| 使用物品 | — | 无检定 | 恢复/道具效果 |
| 逃跑 | DEX对抗 | 玩家DEX vs 最高敌人DEX | 脱出战斗 |

**武器来源**：`Investigator.weapons` 列表包含调查员当前持有的所有武器。战斗中可选武器从此列表生成。若空列表则只有拳击和踢击。

每个 weapon 有：
- `name`: 武器名
- `skill_used`: 关联技能（如"射击(手枪)"、"格斗(剑)"）
- `damage`: 伤害公式（如 "1D10"、"1D6+1"）
- `range`: "近战" | "中距离" | "远距离"
- `ammo`: 弹药数（0 表示近战武器）

**回避限制**：连续回避递减（第二次回避-20%，第三次-40%），防止无限防守。

## 敌人行动

纯规则驱动。`EnemyInstance` 持有 `LibraryEnemy` 的 `attacks` 列表：

```json
{
  "attacks": [
    {"name": "噬咬", "damage": "1D8+DB", "weight": 3},
    {"name": "利爪", "damage": "1D6+DB", "weight": 2}
  ]
}
```

### 攻击选择

按 weight 加权随机。无 weight 字段则等权重：

```python
def select_attack(attacks):
    weights = [a.get("weight", 1) for a in attacks]
    return random.choices(attacks, weights=weights)[0]
```

### 目标选择

优先级：上一轮攻击了此敌人的玩家 > 距离最近 > 随机。当前所有敌人视为同一场景内（距离不考虑）。

### 攻击检定

攻击方投 D100 vs 攻击技能值（敌人用 DEX+POW/2 作为基础攻击值）。玩家有回避机会：
- 玩家本回合选择了"回避" → 攻击自动失败
- 否则玩家可投回避 D100 vs 回避值 → 成功则闪避

### 特殊能力

`special_abilities` 列表在特定时机触发：
- `"盲感"`：对潜行检定为硬性难度 → 若玩家使用了潜行相关动作，检定难度+1级
- `"恐惧灵气"`：首次进入战斗需 SAN 检定
- `"狂暴"`：HP 低于一半时每轮攻击两次

特殊能力由战斗系统在对应时机（进入战斗、回合开始、HP 变化等）按 desc 文本匹配触发，不预定义 hardcode。未来可作为 `[trigger]:[effect]` 结构化，当前保留自然语言 + 接口。

### LLM 增强接口

每轮敌人行动后，可选调 `evaluate_combat_enhancement()`（类似 trait enhancement）：
- 输入：敌人 combat_behavior + 本轮 player actions + 战况
- 输出：是否使用特殊战术、改变目标选择等

当前阶段保留接口，不实现（纯规则驱动）。

## 伤害计算

```
命中 → 掷伤害骰 → +DB → -护甲 → 最终伤害 → 扣 HP
```

### DB (Damage Bonus)

```python
def calc_db(STR: int, SIZ: int) -> str:
    total = STR + SIZ
    if total <= 64:   return "-2"
    if total <= 84:   return "-1"
    if total <= 124:  return "0"
    if total <= 164:  return "+1D4"
    if total <= 204:  return "+1D6"
```

### 护甲

- 敌人护甲：固定减伤值（`enemy.armor`，如 "2点厚皮" → 减2）
- 玩家护甲：目前无，后续由物品系统提供

### 掷骰

伤害公式如 `"1D6+DB"` → 先掷 1D6，再掷 DB（如 +1D4 → 掷 1D4），求和。护甲减免后不能低于 0。

## 战斗结束

| 结果 | 条件 | 处理 |
|------|------|------|
| 胜利 | 所有敌人 HP ≤ 0 | 返回 CombatResult(outcome="win") |
| 失败 | 玩家 HP ≤ 0 | 返回 CombatResult(outcome="loss") |
| 脱出 | 玩家逃跑成功 | 返回 CombatResult(outcome="flee") |

玩家死亡不直接触发结局。`game_loop` 收到 `loss` 后：
1. 检查是否有匹配的 `##END_` 结局条件
2. 有 → 触发对应结局
3. 无 → 主循环决定（可回退到检查点、显示死亡信息、或继续探索）

## 叙事输出

每轮结束调 LLM 生成叙事。与现有 `evaluate_failure_penalty` / `trait_enhancement` 模式一致：

```python
def evaluate_combat_round_narrative(
    combat_log: list[CombatAction],    # 本轮所有机械结果
    enemy_descriptions: list[str],     # 敌人外观/行为描述
    scene_context: str,                # 战斗场景
    player_name: str,
) -> dict:
    # flash, json_mode, thinking=False
    # → {"narrative": "沉浸战斗描写...", "scene_hint": ""}
```

输出给玩家：
```
[机械] ✓ 拳击 成功 | D100=22/50 | 伤害 1D3+0=2 | 深潜者A HP 16→14
[叙事] 你一拳砸在深潜者湿滑的面部，那生物发出一声刺耳的嘶叫，踉跄后退。
```

## 与 game_loop 集成

战斗进入判定由 parse→enrich 主循环完成（见 `2026-05-19-combat-entry-detection-design`）。判定产出的 `CombatInit` 由主循环传至 CombatSystem。战斗系统只负责收到 `CombatInit` 后的回合执行。

```python
# 主循环调用方（战斗进入判定产出 CombatInit 后）:
cs = CombatSystem(world, weapon_lib)
combat_result = cs.run_combat(combat_init)
# 战斗结束 → world.enemy_manager.exit_combat(combat_result)
# loss → 主循环检查结局
```

CombatSystem 不关心 `CombatInit` 从哪来（parse→enrich 判定的 combat_pending，或对峙阶段，或 debug 命令手动触发）。

## 待融合

- **调查员武器**：`Investigator.weapons` 已定义（name/skill_used/damage/range/ammo），战斗系统直接读取
- **武器库**：`data/library/core/weapons.json` 已有 10 件标准武器，`WeaponLibrary` 可直接查询
- **EnemyManager**：由进入判定设计覆盖，战斗系统通过 `CombatInit.enemies` 获取 `EnemyInstance` 列表

## 改动文件

| 文件 | 改动 |
|------|------|
| `src/game/combat.py` | 新建 — CombatSystem, CombatState, CombatAction, 伤害计算, 掷骰 |
| `src/game/messages.py` | 新增 CombatResult 消息类型（如不在进入判定设计中已定义） |
| `src/game_loop.py` | 新增 combat_pending 分支 → CombatSystem.run_combat() |
| `src/investigator/models.py` | 取消 `combat_check()`/`damage_roll()` 的 NotImplementedError，实现 |
| `src/llm.py` | 新增 `evaluate_combat_round_narrative()` — LLM 战斗叙事生成，flash/json_mode/thinking=False |
| `src/prompts.py` | 新增 `build_combat_narrative_prompt()` |
