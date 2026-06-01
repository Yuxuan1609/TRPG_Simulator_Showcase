# Time System Redesign

日期：2026-05-22
状态：设计完成
范围：`scenario_core.py`（基础时钟）、`game/agents/time_agent.py`（新建）、`game/agents/author.py`（time_pressure 管理）、`game/agents/keeper.py`（集成调度）、`prompts.py`（时间上下文注入）、`game/messages.py`（通信包）、`module_designer/layered_parser.py`（Phase 2 时段标准化 + Step 1a/1b total_duration）、`module_designer/l3_designer.py`（time_pressure）、`module_designer/layered_pipeline.py`（管线集成）、`data/library/core/time_costs.json`（新建）

## 动机

原设计过于结构化：抽象 TU 不便追踪，5 种 countdown type 写死，TimeAgent 与时间压力的关系不清晰。重设计思路：用真实分钟计数、半结构化指南替代写死规则、TimeAgent 与 time_pressure 分离为两个独立系统并通过通信包调度。

核心原则：**真人 KP 不会用表格管理时间，而是凭经验和模组指南弹性判断**。

## 基础时钟

`ScenarioWorld` 新增：

```python
game_time: int = 0  # 累计分钟数，唯一时间源

@property
def day(self) -> int:
    return self.game_time // 1440

@property
def hour(self) -> int:
    return (self.game_time % 1440) // 60

@property
def time_of_day(self) -> str:
    h = self.hour
    if h < 5:   return "夜间"
    if h < 8:   return "早晨"
    if h < 17:  return "白天"
    return "黄昏"

def get_time_flags(self) -> dict:
    return {
        f"day:{self.day}": True,
        f"time:{self.time_of_day}": True,
    }
```

**时段标准化**（4 段）：

```
夜间(20-5) → 早晨(5-8) → 白天(8-17) → 黄昏(17-20)
```

Phase 2 prompt 加一行标准名称（类似场景名处理）。

`time_flags` 按需注入 `runtime_state`，entity requirement 直接引用：
```
requirement: "time:夜间 AND day:1"
```

`parse_hard_requirement` 已原生支持。

## 时间推进

### time_costs.json（半结构化参考库）

`data/library/core/time_costs.json`：

```json
{
  "search": {
    "guideline": "快速扫视约1-3分钟；搜查标准房间约5-15分钟；搜索开放空间或大厅约10-30分钟；彻底翻查每个角落约15-45分钟。以房间大小和仔细程度为参考变量。",
    "override": {}
  },
  "move": {
    "guideline": "同场景内移动约1-3分钟；移动到相邻车厢/房间约2-5分钟；长距离或复杂路径约5-15分钟。以路径障碍程度为参考变量。",
    "override": {}
  },
  "dialogue": {
    "guideline": "简短对话约1-5分钟；深入交谈约5-15分钟。以话题深度和信息交换量为参考变量。",
    "override": {}
  },
  "combat_round": {
    "guideline": "每轮战斗约6-12秒。以参与者数量和动作复杂度为参考变量。",
    "override": {}
  }
}
```

`override` 供模组特定覆盖，管线生成 L2 时可写入具体值。

### advance_time()

```python
def advance_time(self, entity, user_input: str, time_costs: dict) -> int:
    """推进时间，返回实际推进的分钟数"""
    category = entity.time_category or self._infer_category(entity)
    guideline = time_costs.get(category, {}).get("guideline", "")
    entity_range = entity.extra.get("time_range") if entity.extra else None
    # KP parse (LLM) 基于 guideline + user_input + entity_range 弹性决定 delta
    delta = self._resolve_time_delta(entity, user_input, guideline, entity_range)
    self.game_time += delta
    return delta
```

### 默认时间范围

未标注 entity 时，KP 基于 `time_costs` guideline 推断。极端 case：
- search 默认参考 guideline
- move 默认参考 guideline
- 其他 entity 默认 3-10 分钟
- 纯叙事回合（"other"）默认 1-5 分钟

## TimeAgent

独立 LLM sub-agent，不维护时间压力（由 Author 管理）。

### 触发条件

- 进入新场景
- `game_time` 距上次调用超过 30 分钟
- Author 通过 time_pressure 判定需要介入时（Author 发送通信包回执）

### 输入

```
当前时间：{game_time}分钟 (第{day}天 {time_of_day} {hour}时)
玩家最近行动：{memory.recent_summary}
当前场景：{current_location}
场景描述：{scene_description}
时间消耗参考：{time_costs guideline}
```

### 输出

```json
{
  "time_delta": 0,
  "narrative_hint": "时间相关的叙事提示",
  "signal_hint": "从 key_signals 选取的当前信号（可为空）"
}
```

- `time_delta`：额外推进的分钟数（如"睡觉"跳 8 小时），默认 0
- `narrative_hint`：注入 enrich/narrator prompt
- `signal_hint`：可选，覆盖 time_pressure 当前阶段的信号

### 调用参数

- 模型：`deepseek-v4-flash`
- thinking：disabled
- json_mode=True
- max_tokens：300

## TimePressure（Author 管理）

### L3 格式

```json
{
  "time_pressure": {
    "name": "吞噬逼近",
    "guide": "后方巨嘴持续吞噬车厢。玩家探索推进正常则每30分钟吞噬一节后方车厢。若玩家反复搜索同一区域或长时间停留——提示震动加剧、声音逼近。若一个半小时内无实质性推进——强制执行吞噬当前车厢尾部区域。",
    "urgency": 0,
    "urgency_max": 10,
    "key_signals": [
      "远处低沉的咀嚼声",
      "脚下车厢轻微震动",
      "后方金属撕裂声",
      "车厢连接处扭曲变形"
    ]
  }
}
```

- `guide`：纯自然语言执行手册，给 Author 和 TimeAgent 当参考
- `urgency`：0 起始，Author 每次通信后决定是否调整
- `urgency_max`：参考上限
- `key_signals`：信号库，Author 根据当前阶段选取

### 与 Author 的关系

time_pressure 由 Author Agent 持有和管理。Author 已有 L3 数据，自然扩展：

```python
class Author:
    def __init__(self, l3_data):
        self.time_pressure = l3_data.get("time_pressure")  # 0-1 个

    def assess_time_pressure(self, comms_packet: TimeCommsPacket) -> dict:
        """收到 Keeper 通信后，基于 time_pressure + L3 判断是否需要介入。
        返回：{should_press: bool, patch: ModulePatch|None, urgency_update: int|None}"""
```

当 `should_press=True` 时，复用现有 Patch 机制生成 AT 或其他 Entity 催促玩家。生成的 entity 带有 narrative 信号，通过正常流程 inject。

## 通信包调度

### TimeCommsPacket

```python
@dataclass
class TimeCommsPacket:
    game_time: int              # 当前分钟数
    day: int
    time_of_day: str
    current_scene: str
    player_actions: str         # 玩家最近行动摘要（≤200 字）
    world_state: str            # 世界状态概述（场景变化/NPC状态/关键事件，≤200 字）
```

总长度控制在 500 token 以内。

### 通信频率

管线 Step 1a/1b 阶段估算 `estimated_duration`（模组预计总时长，分钟），写入 L2 `module_meta`。`comms_interval` 由管线或模组设计者设定，推荐参考值：

- 短模组（≤2h）：6-8 分钟
- 中型模组（2-6h）：10-15 分钟
- 长模组（6-24h）：15-20 分钟
- 超长模组（≥24h）：1-2 小时

最小 floor 5 分钟，防止极短模组通信过密。`comms_interval` 写入 L2 `module_meta.comms_interval`，运行时读取。

**每轮上限**：无论 `game_time` 推进多少，单次 `process_turn` 最多发送 1 个通信包。跨越多倍间隔时也只发 1 次，保证不阻塞回合流。

### 调度流程

```
entity 执行 → advance_time() → game_time 推进 → time_flags 更新
    ↓
game_time 跨越了 comms_interval 的整数倍边界？（上次通信时间 < N*interval ≤ 当前时间）
    ↓ Y（每轮最多 1 次）
Keeper 构建 TimeCommsPacket → Author.assess_time_pressure()
    ├─ should_press=False → 继续
    └─ should_press=True → Author 生成 Patch(AT/Entity, 含信号 narrative)
        → integrate → 下一回合 parse 生效
```

## 完整运行时流程

```
entity 执行
    ↓
advance_time(entity.extra.time_range, user_input)
    ├─ 读 time_costs guideline
    ├─ 弹性取 min~max 之间的值
    └─ game_time += delta
    ↓
time_flags 自动注入 runtime_state
    ↓
TimeAgent 触发？（新场景 或 超过30分钟 或 Author 回执要求）
    ├─ Y → TimeAgent.assess() → time_delta, narrative_hint, signal_hint
    └─ N → 跳过
    ↓
通信包触发？（game_time 跨越 comms_interval 边界）
    ├─ Y → Keeper 构建 TimeCommsPacket → Author.assess_time_pressure()
    │     ├─ should_press → Patch(AT/Entity) → integrate → 下回合生效
    │     └─ no_press → 继续
    └─ N → 继续
    ↓
enrich/narrator 注入 time_context (narrative_hint + signal_hint)
    ↓
requirement 时间条件（time:夜间, day:1）在 parse/判断阶段自动过滤 entity
```

## Prompt 时间注入

各阶段在 prompt 中追加时间感知段：

```
【时间感知】
当前时间：第{day}天 {time_of_day}（累计{game_time}分钟）
{time_context}
{signal_hint}
```

- **Parse**：含时间感知，让 LLM 在意图匹配时考虑时间因素
- **Enrich**：含时间感知 + narrative_hint
- **Narrator**：含时间感知 + narrative_hint + signal_hint

## 实现范围

### 新建文件

| 文件 | 内容 |
|------|------|
| `src/game/agents/time_agent.py` | TimeAgent 类 |
| `data/library/core/time_costs.json` | 半结构化时间消耗参考库 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `scenario_core.py` | ScenarioWorld 加 `game_time` + day/hour/time_of_day property + `advance_time()` + `get_time_flags()` |
| `game/messages.py` | 加 `TimeCommsPacket` dataclass |
| `game/agents/keeper.py` | process_turn 集成 advance_time + TimeAgent 触发 + 通信包调度 |
| `game/agents/author.py` | Author 加 `assess_time_pressure()` + time_pressure 持有 |
| `prompts.py` | Parse/Enrich/Narrator prompt 加 `【时间感知】` 段；parse prompt 加 time_costs guideline 注入 |
| `module_designer/layered_parser.py` | Phase 2 prompt 加"标准时段名称"；Step 1a/1b 输出加 `estimated_duration` |
| `module_designer/l3_designer.py` | L3 数据模型加 `time_pressure` 字段 |
| `module_designer/layered_schema.py` | Schema 验证加 time_pressure |
| `module_designer/layered_pipeline.py` | 管线流程集成 time_costs 加载 + estimated_duration 计算 |
| `game_loop.py` | init_game 加载 time_costs.json |

### 不改动

- `game/judge.py` — 时间条件已通过 runtime_state + parse_hard_requirement 支持
- `game/enemy_manager.py` — 不受时间系统影响
- `game/combat.py` — 战斗时间由 combat_round guideline 覆盖，CombatSystem 不感知时钟
