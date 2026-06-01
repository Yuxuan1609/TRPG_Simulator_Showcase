# ScenarioWorld 重构设计

日期：2026-05-22
状态：设计完成
范围：`scenario_core.py`（拆分为 Facade + GameClock）、`src/utils.py`（markup 解析迁入）、`src/game/agents/keeper.py`（适配 World 新接口）、`src/game/agents/time_agent.py`（保留轻量计时评估器）

## 动机

NEXT-SESSION.md A1 已标注：ScenarioWorld 呈 God object 趋势。当前 1391 行的 `scenario_core.py` 混合了图导航、时间、NPC 状态、武器追踪、敌人追踪、记忆管理、side effect 应用等职责。本次重构目标：**ScenarioWorld 退化为一级 Facade，组合 5 个子系统类，markup 解析抽到 utils，side effect 应用分布到各 Manager**。

## 架构总览

```
ScenarioWorld (一级 Facade — 状态容器 + 查询方法)
├── clock: GameClock              # 二级 — 纯确定性计时器
├── memory: MemoryManager         # 二级 — 已独立
├── enemies: EnemyManager         # 二级 — 已独立
├── npcs: NPCManager              # 二级 — 已独立
├── bosses: BossManager           # 二级 — 已独立
│
└── 本体保留:
    ├── graph: DirectedGraph (场景/事件结构)
    ├── player: Investigator (调查员引用)
    ├── current_location: str
    ├── background_story: str
    ├── wr0_enabled: bool
    ├── scene_weapons: dict (轻量追踪，武器拾取后由 Investigator 管理)
    ├── weapon_library: Any
    ├── _runtime_state: dict[str, NodeRuntimeState]
    ├── _dependency_graph: dict
    │
    └── 查询/操作方法:
        ├── mark_completed / is_completed / get_runtime_state
        ├── check_requirements / check_edge_requirements
        ├── move / get_current_description / get_possible_exits
        ├── get_available_interactions / get_scene_summary / get_scene_info
        ├── to_dict / from_dict / save_state / load_state
        └── (事件追踪: triggered_events / completed_interactions 保留在 World)
```

**RuntimeState 不拆出独立类**：本质上是对两个 dict 的 CRUD + `parse_hard_requirement` 纯函数调用。拆出去只是多一层间接。World 本体直接暴露这些查询方法。

**Keeper 是 World 的管理者/编排者**：通过 World 提供的公开方法操作各子系统，不直接访问子系统的内部状态。

---

## 1. GameClock — 纯确定性计时器

### 文件：`src/game/clock.py`（新建）

```python
class GameClock:
    """纯确定性计时器。不做 LLM 调用，不做叙事判断。"""

    def __init__(self, start_time: int = 0):
        self.game_time = start_time      # 累计分钟
        self.time_context: str = ""      # Author 写入的叙事时间上下文

    # 只读属性
    day: int           # game_time // 1440
    hour: int          # (game_time % 1440) // 60
    time_of_day: str   # "夜间" / "早晨" / "白天" / "黄昏"

    def advance_time(self, minutes: int): ...
    def get_time_flags(self) -> dict[str, bool]: ...

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "GameClock": ...
```

从 ScenarioWorld 迁移：
- 字段：`game_time`、`time_context`（去掉 `_last_comms_time` 和 `comms_interval`——那是 Keeper 调度状态）
- 属性：`day`、`hour`、`time_of_day`
- 方法：`advance_time()`、`get_time_flags()`

### ScenarioWorld 适配

```python
world.clock.game_time              # 替换 world.game_time
world.clock.advance_time(delta)    # 替换 world.advance_time(delta)
world.clock.time_of_day            # 替换 world.time_of_day
world.clock.time_context           # 替换 world.time_context
```

---

## 2. RuntimeState → 融入 World 本体

### 改动

`ScenarioWorld` 保留 `_runtime_state: dict[str, NodeRuntimeState]` 和 `_dependency_graph: dict`，公开方法：

```python
# 状态读写
def mark_completed(self, entity_id: str, tier: str) -> None
def is_completed(self, entity_id: str) -> bool
def get_runtime_state(self, entity_id: str) -> NodeRuntimeState

# 依赖查询
def check_requirements(self, entity: Entity) -> tuple[bool, str]
def check_edge_requirements(self, entity_id: str) -> tuple[bool, str]
def get_incoming_edges(self, entity_id: str) -> list[dict]

# 硬条件解析（委托给模块级纯函数）
def parse_hard(self, hard_str: str) -> bool  # 内部调 parse_hard_requirement()
```

`parse_hard_requirement()` 保留为模块级纯函数在 `scenario_core.py`，由 World 方法内部调用。

### NPC 状态读取

World 通过 `self.npcs`（NPCManager）读取 NPC 状态用于条件判定，而非自己的 dict。

移除 `self.npc_states: dict`（遗留字段），`set_npc_state()`/`get_npc_state()` 代理到 `self.npcs.set_state()`/`self.npcs.get().state`。

---

## 3. Markup 解析 → utils.py

### 迁移

`_MARKUP_PATTERN`、`_parse_kwargs()`、`parse_markup()`、`parse_markup_all()` → `src/utils.py`

Side effect dataclass（`SpawnEnemy`、`StatChange`、`ItemGain` 等）保留在 `scenario_core.py`，因为 Entity/Interaction 等数据模型也在那里，不希望 `utils.py` 依赖 `scenario_core.py`。

或者：side effect dataclass 跟 markup 解析函数一起迁到 `src/utils.py`，因为它们是纯数据定义，不从属 scenario_core。

**决定**：dataclass + 解析函数一起迁到 `src/game/side_effects.py`（新建）。`messages.py` 是 Keeper 专用的消息类型，side effect 是更底层的数据定义，分开更清晰。`scenario_core.py` 重新 import 它们以维持外部兼容。

---

## 4. Side Effect 应用 → 分布

`apply_side_effects()` 拆散，每种 effect 由对应子系统处理：

| dataclass | 应用方法 | 位置 |
|-----------|---------|------|
| `ItemGain` | `investigator.item_manager.add()` | Investigator |
| `ConsumeItem` | `investigator.item_manager.remove()` + LLM 模糊匹配 | Keeper（LLM 部分）|
| `StatChange` | `investigator.modify_stat()` + LLM 叙事更新 | Keeper（LLM 部分）|
| `SpawnEnemy` | `enemy_manager.spawn()` | EnemyManager（已有）|
| `GrantWeapon` | `investigator.add_weapon()` + scene_weapons 清理 | Keeper |
| `NPCStateChange` | `npc_manager.set_state()` | NPCManager（已有）|
| `NPCFollow` | `npc_manager.set_following()` | NPCManager（已有）|

Keeper 中新增方法 `_apply_side_effects(side_effects: list)` 替代原来的 `world.apply_side_effects`（指向模块级函数）。

---

## 5. TimeAgent / GameClock 关系

- **GameClock**：确定性。只管计数，不调 LLM。
- **TimeAgent**（`game/agents/time_agent.py`，保留）：轻量 LLM 评估器。读 Clock 状态，返回评估结果，Keeper 决定是否应用。

**触发时机**（Keeper 判断）：
- enter new scene
- "other" 事件（玩家自由行动）
- 距上次 TimeAgent 调用已过 2-3 回合

**流程不变**：
```
TimeAgent.assess(clock.game_time, clock.day, clock.time_of_day, ...) → result
Keeper: if result.time_delta > 0 → clock.advance_time(result.time_delta)
```

---

## 6. ScenarioWorld 初始化

```python
class ScenarioWorld:
    def __init__(self, graph, start_node, *,
                 background_story="", wr0_enabled=False,
                 enemy_library=None, weapon_library=None,
                 boss_library=None, boss_encounters=None):
        self.graph = graph
        self.current_location = start_node
        self.player = None
        self.background_story = background_story
        self.wr0_enabled = wr0_enabled

        # 子系统
        self.clock = GameClock()
        self.memory = MemoryManager()
        self.enemies = EnemyManager(enemy_library) if enemy_library else None
        self.npcs = NPCManager()
        self.bosses = BossManager(boss_library, boss_encounters) if boss_library else None

        # 本体
        self.scene_weapons: dict[str, list[SceneWeapon]] = {}
        self.weapon_library = weapon_library
        self.triggered_events: dict[str, bool] = {}
        self.completed_interactions: dict[str, set[str]] = {}
        self._runtime_state: dict[str, NodeRuntimeState] = {}
        self._dependency_graph: dict = {}
```

**关键变化**：
- 不再有 `hasattr(world, 'npc_manager')` 惰性检查——`world.npcs` 永远存在
- 不再有 `hasattr(world, 'enemy_manager')`——`world.enemies` 永远存在（可能为 None）
- BossManager 挂在 World 上而非仅传给 Keeper
- 去掉 `npc_states: dict`（NPCManager 是唯一真源）

---

## 7. 序列化适配

`ScenarioWorld.to_dict()` / `from_dict()` 需适配：
- `clock` → GameClock.to_dict/from_dict
- `npcs` → NPCManager.to_dict/from_dict
- `enemies` → EnemyManager.to_dict/from_dict
- `bosses` → BossManager 需要加序列化（当前缺失）
- 移除 `npc_states`
- `modified_descriptions` 保留（用于 persist LLM 运行时修改过的 node descriptions）

---

## 8. 实现步骤

| Step | 内容 | 影响文件 |
|------|------|----------|
| 1 | 新建 `GameClock` 类 + 单元测试 | `src/game/clock.py`（新）, `tests/` |
| 2 | markup 解析函数 + dataclass 迁到新位置 | `src/utils.py` 或 `src/game/side_effects.py`, `scenario_core.py` |
| 3 | ScenarioWorld 重构：移除 npc_states、挂载子系统、整合 RuntimeState 方法 | `scenario_core.py` |
| 4 | BossManager 添加序列化 | `src/game/boss_manager.py` |
| 5 | Keeper 适配 World 新接口 + _apply_side_effects 重写 | `src/game/agents/keeper.py` |
| 6 | game_loop.py / judge.py / narrator.py / author.py 适配 | 各文件 |
| 7 | 运行测试套件，修复回归 | `tests/` |
| 8 | 清理死代码（EncounterAnchor、O3 comment 等已知断点） | `scenario_core.py` |

---

## 9. 不做

- 不改 TimeAgent 的功能范围（仍是纯计时评估器，countdown 属 Author）
- 不拆 Entity/Node/Edge/DirectedGraph（核心数据模型，稳定性优先）
- 不改 MemoryManager 接口
- 不改 combat.py / curator.py / intent_detector.py
