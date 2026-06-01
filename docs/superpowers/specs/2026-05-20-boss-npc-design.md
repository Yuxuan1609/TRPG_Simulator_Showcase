# Boss/剧情敌人 & NPC 机制 — 设计文档

日期: 2026-05-20

## 1. 概述

### 1.1 目标

在现有 TRPG 调查员助手框架上新增两个扩展系统：

- **Boss/剧情敌人**：故事绑定的特殊对抗实体，机制性战斗，LLM 驱动规则解析
- **NPC 机制**：NPC 对话、态度追踪、被动跟随，架构预留升级到半主动

### 1.2 设计原则

- 复用现有模式（Manager + Instance + Library，Entity 三部曲）
- Boss/NPC 数据独立于普通敌人，不耦合
- 灵活字段 + LLM 解读，避免过度结构化

---

## 2. Boss/剧情敌人

### 2.1 Boss 库 (`data/library/core/bosses.json`)

独立于 enemies.json，格式更自由：

```json
{
  "吞噬之口": {
    "name": "吞噬之口",
    "type": "神话生物",
    "attributes": {"STR": 200, "CON": 300, "SIZ": 250, "DEX": 10, "POW": 150},
    "armor": "10点厚皮（常规武器无效，需环境交互破解）",
    "attacks": [
      {"name": "吞噬车厢", "damage": "即死", "notes": "每3轮吞噬一个车厢"}
    ],
    "special_abilities": [
      {"name": "不可阻挡", "desc": "常规武器攻击无效"}
    ],
    "san_loss": "1D10/1D100",
    "description": "来自异界的巨大吞噬之口，不断吞噬列车后方的车厢...",
    "boss_mechanics": "弱点为驾驶室控制面板——需同时持有操作面板钥匙并通过电气维修/操作重型机械检定切断其与列车连接。击败触发END2（列车幸存），被吞噬触发END3，逃离触发END1。",
    "flags": ["boss"]
  }
}
```

**关键设计**：`boss_mechanics` 是**单一自然语言字段**，包含弱点、环境交互、故事结局绑定。由 LLM（CombatSystem 战斗轮解析 + BossManager 战后结算）统一解读，不做结构化拆分。

### 2.2 BossLibrary (`src/library/bosses.py`)

加载 bosses.json，对标 EnemyLibrary：

```python
class BossLibrary:
    def __init__(self, core_path: str, extensions_dir: str = None): ...
    def get(boss_ref: str) -> LibraryBoss: ...
```

### 2.3 Boss Entity（L2 层）

Boss 作为独立 Entity 类型 `boss_encounter`，不进现有 Entity graph。存储在 L2 的顶层字段 `boss_encounters`：

```json
{
  "boss_encounters": [
    {
      "id": "BOSS_1",
      "type": "boss_encounter",
      "engage_type": "at",
      "boss_ref": "吞噬之口",
      "scene": "6号车厢",
    "requirements": "(I3a OR I5b) || 玩家持有驾驶室钥匙且知晓控制面板的操作方法",
    "description": "吞噬之口逼近，你需要操作控制面板切断它与列车的连接"
    }
  ]
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识 |
| `type` | 固定 `"boss_encounter"` |
| `engage_type` | `"at"` / `"interaction"` / `"event"` |
| `boss_ref` | 指向 Boss 库 |
| `scene` | 所在场景（event 类型可为空） |
| `requirements` | COC 7th 需求格式，对齐现有 Entity 的 requirements |
| `description` | 进入战斗时的情境描述 |

- `engage_type="at"`：场景切换时硬性过滤检测
- `engage_type="interaction"`：Parse 阶段识别时检测
- `engage_type="event"`：Judge 完成后全局检测

`requirements` 格式对齐现有 Entity 的 `(hard_conditions) || soft_conditions` 语法。`||` 前为确定性条件（runtime_state 依赖链），`||` 后为自然语言软性条件（LLM 判定）。

### 2.4 BossManager (`src/game/boss_manager.py`)

```python
class BossManager:
    def __init__(self, boss_library: BossLibrary, boss_encounters: list[dict]):
        self.library = boss_library
        self.encounters = boss_encounters  # 来自 L2
        self.active_boss_id: str | None = None  # 当前活跃的 boss encounter

    def check_by_engage_type(self, engage_type: str, *, scene: str = None) -> list[dict]:
        """硬性过滤：返回指定 engage_type、且 requirement 满足的 boss entities"""

    def build_combat_init(self, boss_entity: dict, player, scene: str) -> CombatInit:
        """boss_ref → BossLibrary.get() → 构造 EnemyInstance（含完整属性/attacks/armor/hp）→ CombatInit"""
    
    def check_requirements(self, boss_entity: dict, world) -> bool:
        """解释 || 语法：(硬性条件) || 软性条件 → 硬性部分走 Judge.parse_hard_requirement，软性部分 LLM 判定"""

    def resolve_outcome(self, combat_result: CombatResult):
        """战后结算：LLM 解读 boss_mechanics + outcome → 设置结局标记 / NPC 状态变化"""
        # 信息挂钩+规则整合，不参与战斗回合本身
```

**触发时机**：

| engage_type | 检查时机 | 调用 |
|-------------|---------|------|
| `"at"` | 场景切换后 | `BossManager.check_by_engage_type("at", scene=...)` |
| `"interaction"` | Keeper.parse 命中 boss entity 时 | `BossManager.check_by_engage_type("interaction")` |
| `"event"` | Keeper.judge 完成后 | `BossManager.check_by_engage_type("event")` |

**不涉及 spawn**：Boss 不走 `@spawn_enemy` 路径。条件满足 → 直接从 BossLibrary 获取数据构造 EnemyInstance → 进入战斗。

### 2.5 CombatSystem 扩展 (`src/game/combat.py`)

**现有缺陷**：EnemyInstance 缺少战斗属性（attributes/attacks/armor/hp），CombatSystem 用 `hasattr` fallback 勉强兼容。

**扩展点**（最小化改动）：

1. **属性桥接** — `BossManager.build_combat_init()` 确保 EnemyInstance 携带完整的 attributes/attacks/armor/special_abilities/hp

2. **Boss 行为 LLM 层** — 当 `flags` 包含 `"boss"` 时，`_resolve_enemy_action()` 走 LLM 路径：输入 `boss_mechanics + special_abilities + 当前局势` → LLM 输出攻击/特殊能力/目标/narrative。非 Boss 敌人保持现有确定性路径

3. **环境交互** — `CombatInit` 新增可选字段 `environment_actions: list[dict]`，BossManager 从 `boss_mechanics` LLM 解读出环境交互选项注入战斗。玩家可选择环境交互而非直接攻击

### 2.6 Game Loop 集成

```
init_game():
  + boss_library = BossLibrary("data/library/core/bosses.json")
  + boss_encounters = l2.get("boss_encounters", [])
  + boss_manager = BossManager(boss_library, boss_encounters)

Keeper.process_turn():
  1. parse (LLM)
     + boss_interaction = boss_manager.check_by_engage_type("interaction")
  2. judge (确定)
  2.5 combat_entry (LLM)
     + boss_at = boss_manager.check_by_engage_type("at", scene=world.current_node)
  3. 事件完成后
     + boss_event = boss_manager.check_by_engage_type("event")

  → 任一 boss entity 命中 → boss_manager.build_combat_init() → CombatSystem.run_combat()
  → 战后 → boss_manager.resolve_outcome(result)
```

---

## 3. NPC 机制

### 3.1 合并后的 NPC dataclass (`src/game/npc_manager.py`)

合并 `NPCProfile`（L2）和运行时状态为单一结构：

```python
@dataclass
class NPC:
    # ── 档案字段（Step 2.5 产生，来自 L3 CharacterDesign → LLM 拆解）──
    name: str
    role: str = ""
    personality_notes: str = ""
    appearance: str = ""
    what_they_can_do: str = ""           # 行为能力描述（自然语言）
    interaction_triggers: list[str] = field(default_factory=list)

    # ── 运行时字段（NPCManager 管理）──
    scene: str = ""                      # 当前位置
    attitude: str = "neutral"            # hostile/wary/neutral/friendly/trusting
    following: bool = False              # 是否跟随调查员
    memory: list[str] = field(default_factory=list)  # 对话记忆摘要
    state: str = "alive"                 # alive/injured/dead/left
    extra: dict | None = None            # 预留扩展
```

**与 L3/L2 映射**：

```
L3 CharacterDesign.id              → (NPCManager 内部 dict key)
L3 CharacterDesign.name            → NPC.name
L3 CharacterDesign.behavior        → Step 2.5 LLM 拆解 → .role, .personality_notes, .what_they_can_do
L1 npc_appearances                 → .appearance
L2 关联的 interactions/auto_triggers → .interaction_triggers
```

运行时字段（scene/attitude/following/memory/state）由 NPCManager 在 `init_game()` 时初始化，不在 JSON 中。

### 3.2 NPCManager (`src/game/npc_manager.py`)

```python
class NPCManager:
    def __init__(self):
        self._npcs: dict[str, NPC] = {}

    # ── 初始化 ──
    def init_from_profiles(self, profiles: dict):
        """从 L2 npc_profiles 批量创建 NPC 实例"""

    # ── 查询 ──
    def get(self, name: str) -> NPC | None
    def get_in_scene(self, scene: str) -> list[NPC]
    def get_following(self) -> list[NPC]

    # ── 交互 ──
    def talk_to(self, npc_name: str, player_input: str, llm) -> str:
        """对话：注入 态度/记忆/档案 上下文 → LLM 扮演 NPC 生成回应 → 追加 memory"""

    # ── 状态变更 ──
    def set_attitude(self, name: str, attitude: str)
    def set_following(self, name: str, following: bool)
    def set_state(self, name: str, state: str)
    def move_to(self, name: str, scene: str)

    # ── 跟随同步 ──
    def sync_followers(self, scene: str):
        """所有 following=True 的 NPC 自动移动到 scene"""

    # ── 序列化 ──
    def to_dict(self) -> dict
    def from_dict(self, data: dict, profiles: dict)
```

### 3.3 NPC 与 Entity 系统的剥离

- **管线端**：Step 2.5 识别 NPC entities → 写入 `npc_profiles`，不进 final L2 Entity graph
- **运行时**：Keeper.parse 识别 NPC 交互 → 直接路由到 `NPCManager.talk_to()`，跳过 Judge→Entity 管线
- **对话上下文注入**：Keeper 调用 `NPCManager.get_in_scene(scene)` → 将 NPC 列表注入 Narrator prompt 的场景描述

### 3.4 NPC 跟随

当前实现**被动标签**：

- `@npc_follow(npc_name=X, follow=true)` markup → `NPCManager.set_following()`
- 场景切换 → `NPCManager.sync_followers(scene)` 自动移动
- 场景描述注入跟随 NPC 列表

**预留扩展 hook**（半主动升级路径）：

- `NPCManager.get_ambient_triggers(scene)` → 跟随 NPC 在特定场景的主动行为提示
- 未来对接 AutoTrigger 系统或独立 LLM 判定

### 3.5 Game Loop 集成

```
init_game():
  + npc_manager = NPCManager()
  + npc_manager.init_from_profiles(l2.get("npc_profiles", {}))

Keeper.process_turn():
  1. parse (LLM)
     + 识别为 NPC 交互 → npc_manager.talk_to(name, input, llm)
     + 返回 narrative（跳过 Judge/Entity 管线）
  2. 场景上下文
     + npcs_in_scene = npc_manager.get_in_scene(world.current_node)
     + followers = npc_manager.get_following()
     + 注入 enrich/narrator prompt

场景切换:
  → npc_manager.sync_followers(new_scene)

@npc_state_change(npc_name=X, new_state=Y):
  → npc_manager.set_state(X, Y)
  → 若 state 涉及态度变化，同步 set_attitude

@npc_follow(npc_name=X, follow=true/false):
  → npc_manager.set_following(X, true/false)
```

### 3.6 未来多调查员备注

NPC 战斗参与暂不实现，预留：

- `NPC` dataclass 字段预留 `combat_stats: dict | None = None`
- `CombatSystem._select_enemy_target()` 已标注 "extendable to NPCs later"
- 多调查员时 NPC 可加载简化版 Investigator 属性作为战斗数据

---

## 4. 模组管线改动

### 4.1 Step 1a/1b — 新增识别

Prompt 新增两项识别任务：

```
7. 【Boss/剧情敌人】：从模组原文识别具有特殊机制、故事绑定的对抗实体。
   输出字段：boss_encounters: [{id, boss_name, associated_scene, mechanics_hint}]
8. 【NPC角色】：已有 characters 字段，确保 behavior 标注是否为关键NPC。
```

### 4.2 Step 2 — Boss Entity 生成

Step 2c 新增 sub-step `parse_step2_boss`：将 Step 1 的 `boss_encounters` 结构化生成 L2 boss entities（含 `engage_type` / `requirements`）。

### 4.3 Step 2.5 — NPC Profile 结构对齐

Step 2.5 prompt 输出字段对齐新 `NPC` dataclass：

```
输出：{ "npc_profiles": { "NPC名称": {
  "name", "role", "personality_notes", "appearance",
  "what_they_can_do", "interaction_triggers"
}}}
```

### 4.4 L2 组装 (`_assemble_l2`)

```python
{
    "scenes": scenes,
    "events": events,
    "boss_encounters": boss_encounters,  # 新增
    "npc_profiles": npc_profiles,         # 已有，字段对齐
}
```

NPC interactions/AT entities **不进入** scenes/events（Step 2.5 已提取到 npc_profiles）。

### 4.5 Step 3 — 交叉验证

新增验证项：
- `boss_ref` 与 BossLibrary 的交叉验证
- NPC 名称在 L1↔L2↔L3 的一致性检查

### 4.6 提示词 Review

修改 Boss/NPC 相关提示词后，需全量检查管线所有 prompt：
- Step 1a/1b system prompt（+boss_encounters 识别）
- Step 2c L3 / Step 2.5 NPC profiles
- Phase 2（+@npc_follow markup 解析）
- Step 3a/3b 验证 prompt
- 确保不被新增字段引入的 token 增量超出 LLM 上下文窗口

---

## 5. 新增/@markup

| Markup | 效果 |
|--------|------|
| `@npc_follow(npc_name="", follow=true/false)` | 设置 NPC 跟随状态 |
| `@npc_state_change(npc_name="", new_state="")` | 已有，不变 |

Boss 不使用 @markup（直接走 Entity → BossManager → CombatInit 路径）。

---

## 6. 敌人属性桥接（先决补丁）

当前 `EnemyInstance` 不携带 `attributes`/`attacks`/`armor`/`special_abilities`/`hp`，CombatSystem 全程 `hasattr` fallback。需在 `EnemyManager.spawn()` 中从 LibraryEnemy 拷贝这些字段到 EnemyInstance。

Boss 路径在 `BossManager.build_combat_init()` 中同样确保 EnemyInstance 携带完整属性。

---

## 7. 数据流总览

```
┌──────────┐    ┌─────────────────┐    ┌──────────────┐
│ bosses.json │    │ l2_keeper.json   │    │ game_loop     │
│            │    │                   │    │               │
│ 自由格式    │    │ boss_encounters[] │    │ BossManager    │
│ boss_mech   │───→│  - engage_type    │───→│  - check(eng)  │
│            │    │  - requirements    │    │  - combat_init │
│            │    │                   │    │  - resolve_out │
                │                   │    │               │
                │ npc_profiles{}    │    │ NPCManager     │
                │  - what_they_can_do│───→│  - talk_to()   │
                │  - triggers       │    │  - sync_follow  │
                │  - personality    │    │  - attitude     │
                └─────────────────┘    └──────────────┘
```

---

## 8. 测试策略

| 层级 | 内容 |
|------|------|
| **BossLibrary 单元** | 加载/查询/字段完整性 |
| **BossManager 单元** | engage_type 硬性过滤/requirement 判定/combat_init 构建 |
| **NPCManager 单元** | 初始化/对话/态度变更/跟随同步/序列化 |
| **CombatSystem 属性桥接** | 验证 EnemyInstance 携带完整属性后战斗流程正确 |
| **CombatSystem Boss LLM 路径** | Mock LLM，验证 boss_mechanics 注入到战斗 prompt |
| **管线集成** | Step 1→2→2.5→3 流程中 boss_encounters/npc_profiles 端到端正确 |
| **Game Loop 集成** | init_game 加载 Boss/NPC → run_turn 中正确路由 |

---

## 9. 待确认

- [ ] NPC 对话的 LLM 调用是否独立线程避免阻塞 turn 返回？
- [ ] `boss_mechanics` 自然语言字段的格式规范是否需要约束（目前完全自由）？
