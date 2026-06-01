# TurnMonitor + 自动存档 设计规格

> 日期：2026-05-29 | 状态：待审核

## 背景

当前 Keeper 的 `process_turn()` 是一个大型管线段编排函数（~700 行），包含 13+ 个步骤，混合了同步、并行、异步（早启动晚收集）三种执行模式。任一步骤的 LLM 调用异常都可能导致整个回合崩溃，且失败后无回退机制、无自动存档。

## 目标

1. **TurnMonitor**：管线级状态机，追踪每个 step 的状态转换，关键段失败回退 + freeze，非关键段失败跳过降级。吸收合并现有 `PipelineHealth`。
2. **自动存档**：后台定时器标志位模式，每 10 分钟自动滚动存档，不阻塞 game loop。同时修复缺失的 `save_game` / `load_game` 函数。

---

## Part A: TurnMonitor — 管线 DAG 状态机

### A.1 执行拓扑（真实 DAG）

```
pre_parse ──→ parse ──→ judge ──┬──→ combat_entry ──→ combat_resolve
                     │          │                          │
                     │          ├──→ [enrich ∥ time_agent] │
                     │          │         ↓                │
                     │          │     collect_enrich_ta ←──┘
                     │          │         ↓
                     │          │     boss_at_check ──→ time_pressure
                     │          │         ↓
                     │          └──→ intent_detect (早启动) ──→ collect_intent
                     │                    ↓                       ↓
                     └── npc_interact     author ──→ apply_pending ──→ boss_event_check
                          (可能早退)                                     ↓
                                                                     curate ──→ RETURN
```

### A.2 关键并行关系

| 关系 | 说明 |
|------|------|
| `enrich ∥ time_agent` | 共享 `ThreadPoolExecutor(max_workers=2)`，互不依赖。一个失败不影响另一个 |
| `intent_detect` | 在 judge 阶段 `executor.submit()` 早启动，到 `collect_intent` 阶段 `future.result()` 收集 |
| `combat_entry` | 依赖 `all_outcomes`（judge 完整产出），独立于 intent_detect |
| `boss_at_check` | 必须在 enrich 收集之后（避免跳过 enrich — Debug #36） |
| `author` | 依赖 `detect_future`。可能触发递归 `process_turn()` |

### A.3 步骤分类

| 步骤 | 关键? | 依赖 | 重试后失败行为 |
|------|-------|------|----------------|
| `pre_parse` | 否 | 无 | 跳过，raw 直入 parse |
| `parse` | **是** | pre_parse | 回退 world + freeze |
| `judge` | **是** | parse | 回退 world + freeze |
| `npc_interact` | 否 | parse | 对话失败返回 fallback 文本 |
| `combat_entry` | 否 | judge | 跳过，不进战斗 |
| `enrich` | 否 | judge | 跳过，outcomes 用原始 message |
| `time_agent` | 否 | judge | 跳过，时间不推进 |
| `boss_at_check` | 否 | enrich | 跳过 |
| `time_pressure` | 否 | boss_at | 跳过 |
| `intent_detect` | 否 | judge | 跳过，不进 Author |
| `author` | 否 | intent_detect | 跳过，不扩展模组 |
| `apply_pending` | **是** | author（可选） | 回退 world + freeze |
| `boss_event_check` | 否 | apply_pending | 跳过 |
| `curate` | **是** | apply_pending, boss | 回退 world + freeze |

### A.4 重试策略

- 每个段最多 **2 次重试**（即共 3 次尝试）
- 重试次数通过 `config.py:TURN_STEP_MAX_RETRIES` 可配置（默认 2）
- 不设全局 wall-clock 超时（不同回合复杂度差异大）

### A.5 Freeze 机制

```
回合开始 → TurnMonitor.begin_turn()
  │           └── 深拷贝当前 world state → _last_good_state
  │
  ├── 执行各步骤 ...
  │
  └── 关键段失败（2次重试用尽）
        │
        ├── 从 _last_good_state 恢复 world（完整回退）
        ├── world.save_state("data/autosave/recovery.json")
        └── return {"game_frozen": True, "message": "..."}
```

前端收到 `game_frozen=True` 时：
- 显示冻结覆盖层，禁用输入框
- 提示文本：`"系统异常，游戏已暂停。上一回合的状态已自动保存到 recovery 存档。请使用 /load recovery 恢复，或等待片刻后 /reset 重试。"`

### A.6 数据结构

```python
# src/monitor/turn_monitor.py

@dataclass
class StepResult:
    step: str
    status: str         # pending | running | ok | failed | skipped | retrying
    retries: int
    duration_ms: float
    error: str = ""

class TurnMonitor:
    def __init__(self, sensor: LLMSensor, world: ScenarioWorld):
        self._sensor = sensor
        self._world = world
        self._steps: list[StepResult] = []
        self._last_good_state: dict | None = None

    def begin_turn(self) -> None:
        """快照 world 作为回退点，清空 step 列表"""
        self._last_good_state = self._world.to_dict()
        self._steps.clear()

    def execute_step(self, step: str, fn, *,
                     is_critical: bool = False,
                     max_retries: int = 2) -> StepResult:
        """执行一步。is_critical=True 时，重试耗尽后回退 world + raise TurnFrozenError"""
        ...

    def snapshot(self) -> dict:
        """返回当前回合状态 + LLM 层指标的合并视图。
        取代 PipelineHealth.snapshot()。
        """
        ...
```

`TurnFrozenError` 是内部异常，被 `process_turn()` 的顶层 catch 捕获，统一处理为 freeze 响应。

### A.7 整合关系

```
现有架构                          变更后
──────────────────────────────────────────────────────
LLMSensor                         无变更（仍记录 LLM 调用）
AgentMonitor                      无变更（仍处理 LLM 级降级）
PipelineHealth                    删除 → 逻辑合并入 TurnMonitor.snapshot()
KeeperPolicy                      无变更
TurnMonitor                       **新增** — 管线编排层状态机
```

`/health` 命令（`game_loop.py:94-108`）改为读取 `turn_monitor.snapshot()`，输出包含：
- LLM 调用统计（原 PipelineHealth 数据）
- 当前回合 step 状态列表
- degradation 状态
- freeze 状态

`_push_progress()` WebSocket 推送（`game.py:662-670`）在每次 step 完成后推送 step 状态。

### A.8 Keeper.process_turn() 接入方式

替换现有的裸 `try/except` 和条件分支为 `TurnMonitor.execute_step()` 包装：

```python
# 现有模式（以 parse 为例）
try:
    parse_result = self._parse(raw)
except Exception as e:
    self._warnings.append(f"意图解析失败...")
    return [{"type": "other", "text": raw}]

# 接入后模式
try:
    parse_result = self._monitor.execute_step(
        "parse", lambda: self._parse(raw), is_critical=True)
except TurnFrozenError:
    return self._build_frozen_response()
```

并行段（enrich ∥ time_agent）使用 `execute_parallel()` 方法，内部管理 ThreadPoolExecutor，分别追踪两个 step 的结果。

---

## Part B: 自动存档

### B.1 触发机制

**标志位模式**：后台 daemon 线程定时设置标志，主线程在回合间隙执行存档。

```
Timer Thread (daemon)              Game Loop Thread
──────────────────────              ─────────────────
每 10 分钟:                         回合开始:
  _autosave_flag = True ──────→     检查 _autosave_flag
                                    if True:
                                      world.save_state(path)
                                      _autosave_flag = False
```

**为什么是标志位而非后台直接写**：
- `save_state()` 操作 graph、world、memory、player 等多个对象
- 后台线程写可能在 game loop 读/写同一对象时产生不一致的快照
- 标志位模式将写操作放在主线程的回合间隙（`process_turn` 调用前），此时无状态变更

### B.2 存档文件

| 类型 | 路径 | 行为 |
|------|------|------|
| 自动存档 | `data/autosave/autosave_1.json` ~ `autosave_5.json` | 滚动覆盖，最多保留 5 个 |
| 紧急存档 | `data/autosave/recovery.json` | freeze 时自动写入 |
| 手动存档 | `save_<slot>.json`（根目录） | 玩家 `/save <slot>` 命令，独立不覆盖 |
| 手动读档 | `save_<slot>.json` | 玩家 `/load <slot>` 命令 |

### B.3 配置项（config.py 新增）

```python
AUTOSAVE_ENABLED = True
AUTOSAVE_INTERVAL_SEC = 600       # 10 分钟
AUTOSAVE_MAX_COPIES = 5
AUTOSAVE_DIR = "data/autosave"
```

### B.4 实现位置

| 文件 | 变更 |
|------|------|
| `src/config.py` | 新增 4 个配置项 |
| `src/game_loop.py` | 新增 `save_game()`、`load_game()`、`start_autosave()`、`_autosave_flag` |
| `frontend/routers/game.py` | 修复 `/save` `/load` 对不存在的 `save_game`/`load_game` 的引用；`process_turn()` 入口检查 `_autosave_flag` |
| `src/game_loop.py`（`run_turn`） | 开始前检查 `_autosave_flag`，触发存档 |

### B.5 Bug 修复

`frontend/routers/game.py` L212, L221, L593, L603 引用了不存在的 `from game_loop import save_game, load_game`。修复方案：
- 在 `game_loop.py` 中实现 `save_game(game: dict, path: str)` 和 `load_game(game: dict, path: str)` 包装函数
- `save_game`：调用 `game["keeper"].world.save_state(path)`，同时保存 `keeper.turn_number` 等元信息
- `load_game`：读取存档 → `ScenarioWorld.load_state(path)` → 替换 `game["keeper"].world` 并重建 Keeper 引用

---

## Part C: 文件变更清单

### 新增

| 文件 | 说明 |
|------|------|
| `src/monitor/turn_monitor.py` | TurnMonitor 类和 StepResult dataclass |

### 修改

| 文件 | 变更 |
|------|------|
| `src/monitor/health.py` | 删除或标记 deprecated（合并到 TurnMonitor） |
| `src/game/agents/keeper.py` | `process_turn()` 接入 TurnMonitor.execute_step()；新增 `_build_frozen_response()` |
| `src/game_loop.py` | 新增 `save_game()`、`load_game()`、`start_autosave()`；`/health` 命令改为读 TurnMonitor；`run_turn()` 入口检查 autosave flag |
| `frontend/routers/game.py` | `/save` `/load` 修复；`process_turn()` 入口检查 autosave flag；freeze 响应处理 |
| `src/config.py` | 新增 `AUTOSAVE_*` 4 个配置项；新增 `TURN_STEP_MAX_RETRIES = 2` |
| `frontend/templates/game.html` | 新增 freeze 覆盖层 DOM + JS |

### 测试

| 文件 | 说明 |
|------|------|
| `tests/test_turn_monitor.py` | 单元测试：step 执行/重试/关键段失败回退/snapshot 格式 |

---

## 自审清单

- [x] 无 TBD/TODO 占位符
- [x] 步骤分类与 process_turn() 实际代码一致
- [x] 并行关系（enrich∥TA、intent_detect 早启动）已在状态机设计中体现
- [x] freeze 机制明确：回退 world + 写 recovery 存档 + 前端冻结
- [x] 自动存档方案明确：标志位 + 滚动 + 配置项
- [x] Bug fix 明确：save_game/load_game 缺失
