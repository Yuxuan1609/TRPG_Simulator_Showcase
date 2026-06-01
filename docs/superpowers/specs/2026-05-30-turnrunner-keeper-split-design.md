# TurnRunner + Keeper 职责分离 设计规格

> 日期：2026-05-30 | 状态：待审核

## 背景

`keeper.py` 1650 行，`process_turn()` 900+ 行。Keeper 同时充当"世界操作工具箱"和"回合步骤总指挥"。TurnMonitor 埋在 Keeper 内部仅做 retry wrapper，没有调度权。`game_loop.run_turn()` 又在 Keeper 之上做 narrator/combat/snapshot 后处理，形成三层混叠。

## 目标

1. Keeper → 纯操作集合（toolbox），每个方法是独立可测试的纯函数
2. TurnMonitor → 升级为 **TurnRunner**，作为回合步骤总指挥
3. game_loop → 精简为 TurnRunner 的 thin wrapper（narrator + snapshot）

## 新架构

```
game_loop.run_turn()
      │
      ├─ TurnRunner.execute_turn(keeper, author, turn_input) → TurnResult
      │     │
      │     ├─ pre_parse  (critical=false)
      │     ├─ parse      (critical=true)
      │     ├─ judge      (critical=true)
      │     ├─ combat     (critical=false)
      │     ├─ [enrich ∥ time_agent]  (parallel, critical=false)
      │     ├─ time_pressure          (critical=false)
      │     ├─ intent + author        (critical=false)
      │     ├─ apply_pending          (critical=true)
      │     ├─ boss_event             (critical=false)
      │     └─ curate     (critical=true)
      │
      ├─ narrator.narrate(result.brief) → narrative
      └─ build PlayerFacingSnapshot
```

## Part A: TurnRunner

### 位置

`src/turn_runner.py` — 新建。同时删除 `src/monitor/turn_monitor.py`（逻辑已迁移）。

### 接口

```python
@dataclass
class TurnResult:
    brief: NarratorBrief | None = None
    combat_init: CombatInit | None = None
    standoff_prompt: dict | None = None
    ending: dict | None = None
    time_agent: dict | None = None
    enrich: dict | None = None
    npc_events: list[str] = field(default_factory=list)
    ambiguous_question: str = ""
    frozen: bool = False
    frozen_message: str = ""
    weapon_pickup: bool = False


class TurnRunner:
    def __init__(self, sensor: LLMSensor, world: ScenarioWorld):
        self._sensor = sensor
        self._world = world
        self._steps: list[StepResult] = []
        self._frozen: bool = False
        self._freeze_message: str = ""

    def execute_turn(self, keeper, author, turn_input: TurnInput) -> TurnResult:
        """
        主入口。编排 10+ 步骤，处理重试/并行/freeze。
        keeper 提供所有操作函数，author 提供 L3 动态扩展能力。
        """

    def snapshot(self) -> dict:
        """返回 LLM 调用统计 + 步骤状态。供 /health 命令使用。"""
```

### 步骤 DAG（硬编码在 `execute_turn()` 中）

```
pre_parse ──→ parse ──→ judge ──┬──→ combat ──→ [enrich ∥ time_agent]
                                 │                    ↓
                                 │              time_pressure
                                 │                    ↓
                                 └── intent ──→ author ──→ apply_pending
                                                              ↓
                                                         boss_event
                                                              ↓
                                                           curate
```

### 重试与 Freeze

沿用当前 `execute_step()` + `execute_parallel()` 逻辑，但不再依赖 `_restore_world`（已删除）。Freeze 时直接抛 `TurnFrozenError`，由 game_loop 捕获后告知玩家读取 autosave。

### 与 keeper 的数据契约

每个步骤的输入/输出通过明确的参数和返回类型定义：

| 步骤 | 输入 | 输出 | keeper 方法 |
|------|------|------|-------------|
| pre_parse | raw_text | PreParseResult | `keeper.pre_parse(raw)` |
| parse | resolved_text | list[dict] | `keeper.parse(raw)` |
| judge | parse_result, raw | JudgedResult | `keeper.judge_entities(...)` |
| combat | raw, all_outcomes | CombatInit \| None | `keeper.check_combat_entry(...)` |
| enrich | judged_entities, raw | dict | `keeper.enrich(...)` |
| time_agent | action_summaries, raw | dict | `keeper.run_time_agent(...)` |
| time_pressure | author, outcomes | — | (内联在 TurnRunner) |
| author | author, intent_result | AuthorResponse | `keeper.handle_author(...)` |
| apply | — | — | `keeper.apply_pending()` |
| boss_event | turn_input | CombatInit \| None | `keeper.check_boss_event(...)` |
| curate | outcomes, ambient, emphasis | NarratorBrief | `keeper.curate(...)` |

### 文件变更

| 文件 | 变更 |
|------|------|
| `src/turn_runner.py` | **新建**。TurnRunner + StepResult(dataclass) + TurnFrozenError |
| `src/monitor/turn_monitor.py` | **删除**。逻辑迁移到 turn_runner.py |
| `src/monitor/__init__.py` | 移除 `TurnMonitor`、`TurnFrozenError`、`StepResult` 的导出 |

## Part B: Keeper 精简

### 目标

`keeper.py` 从 1650 行精简到 ~600 行。删除 `process_turn()`、`_build_frozen_response()`、`complete_combat_turn()`。保留所有步骤实现方法，暴露为 public API。

### 暴露接口

```python
class Keeper:
    # ── 步骤操作（TurnRunner 调用）──
    def pre_parse(self, raw: str) -> PreParseResult: ...
    def parse(self, raw: str) -> list[dict]: ...
    def judge_entities(self, parse_result, raw: str) -> tuple[list, EnrichInput]: ...
    def check_combat_entry(self, raw, all_outcomes) -> CombatInit | None: ...
    def check_boss_event(self, turn_input) -> CombatInit | None: ...
    def enrich(self, entities, raw: str) -> dict: ...
    def run_time_agent(self, actions, raw: str) -> dict: ...
    def handle_author(self, author, turn_input, ...) -> AuthorResult: ...
    def apply_pending(self): ...
    def curate(self, outcomes, ambient, emphasis) -> NarratorBrief: ...
    def resolve_standoff(self, state, player_input) -> dict: ...

    # ── 查询（game_loop / TurnRunner 使用）──
    def find_entity_by_id(self, eid: str) -> Entity | None: ...
    
    # ── 内部（保留）──
    def _build_world_brief(self) -> str: ...
    def _build_world_snapshot(self) -> dict: ...
    def _infer_time_category(self, entity) -> str: ...
    def _apply_side_effects(self, effects) -> list[str]: ...
    def _integrate_patch(self, patch): ...
    def _integrate_supplement(self, edit, author): ...
```

### 删除项

- `process_turn()` — 迁移到 TurnRunner
- `_build_frozen_response()` — 迁移到 TurnRunner
- `complete_combat_turn()` — 迁移到 TurnRunner 或 game_loop
- `turn_monitor` 属性 — TurnRunner 不再挂载在 Keeper 上
- `_weapon_offer`、`_weapon_offer_msg` — 迁移到 Keeper 实例属性（不变）

### 保留不变项

- `Judge`、`Curator`、`IntentDetector`、`PreParseDisambiguator` 子组件
- 所有 side_effect 应用逻辑
- NPC 注入逻辑（`_inject_npc_at` — 已简化为 no-op）
- 上下文构建辅助方法

## Part C: game_loop 简化

### 当前 ~500 行 → 目标 ~250 行

```python
def run_turn(game: dict, user_input: str, **libs) -> dict:
    keeper = game["keeper"]
    runner = game["runner"]        # TurnRunner 实例
    narrator = game["narrator"]
    
    _check_autosave(game)
    
    # Handle debug commands (不变)
    if user_input.strip().startswith("/"):
        return _handle_slash_command(...)
    
    # 主回合
    turn_input = TurnInput(raw_text=user_input, player=keeper.world.player)
    try:
        result = runner.execute_turn(keeper, game["author"], turn_input)
    except TurnFrozenError as e:
        return {"game_frozen": True, "frozen_message": str(e), ...}
    
    if result.ambiguous_question:
        return {"brief": result.ambiguous_question, "narrative": result.ambiguous_question}
    
    if result.weapon_pickup:
        return {"brief": result.brief, "weapon_pickup": True}
    
    # Narrator (不变)
    narrative_brief, narrative = narrator.narrate(result.brief, snap=..., user_input=user_input)
    
    # Combat (不变)
    if result.combat_init:
        combat_result = _run_combat(result.combat_init, keeper)
    
    # PlayerFacingSnapshot (不变)
    snapshot = _build_player_snapshot(keeper.world, narrator, result, combat_result)
    
    return {"brief": narrative_brief, "narrative": narrative, "player_snapshot": snapshot, ...}
```

### 新增依赖

`game_loop.init_game()` 中初始化 TurnRunner：

```python
from turn_runner import TurnRunner
runner = TurnRunner(sensor, world)
game["runner"] = runner
```

## Part D: 文件变更清单

| 文件 | 变更 |
|------|------|
| `src/turn_runner.py` | **新建** |
| `src/monitor/turn_monitor.py` | **删除** |
| `src/monitor/__init__.py` | 移除 TurnMonitor 导出 |
| `src/game/agents/keeper.py` | 删除 process_turn()/~500行，抽取 judge_entities() 等方法 |
| `src/game_loop.py` | 精简 run_turn()，新增 _run_combat() helper |
| `frontend/routers/game.py` | `/health` 改为读取 `runner.snapshot()` |
| `tests/test_harness_parallel.py` | `_run_turns()` 调用改为 `runner.execute_turn()` |

## 自审清单

- [x] TurnRunner 步骤 DAG 与当前 process_turn 实际顺序一致
- [x] 并行关系（enrich∥time_agent）在 TurnRunner 中保留
- [x] freeze 依赖 autosave（已删除 _restore_world）
- [x] Keeper 暴露接口覆盖 TurnRunner 所有调用
- [x] game_loop 不再直接调用 keeper.process_turn
