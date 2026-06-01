# Time System Design

日期：2026-05-19
状态：设计阶段
范围：`scenario_core.py`（世界时间基础层）、`game/agents/time_agent.py`（TimeAgent 新模块）、`prompts.py`（时间上下文注入）、`game/judge.py`（requirement 时间条件）、L2/L3 格式（countdown + extra）

## 动机

当前系统无时间概念。玩家可以无限停留、无限重试。COC 模组中时间是一个核心叙事工具——倒计时逼近的威胁、昼夜切换营造的不同氛围、调查推进与时间流逝的交互感——这些都无法用纯回合计数或预定义阈值很好地表达。

核心设计原则：**时间不是计数器，是叙事引导机制**。

## 两层架构

### 基础层：世界时间（确定性）

`ScenarioWorld` 维护一个简单时钟，不做推理，只做事实记录和默认推进：

```python
# ScenarioWorld 新增字段
self.game_time: int = 0          # 抽象时间单位，累计
self.time_of_day: str = ""       # 早晨/中午/下午/黄昏/夜间
self.time_context: str = ""      # TimeAgent 最近输出的叙事上下文（注入 prompt 用）
```

**默认 time_cost**（entity 未指定时使用，可被 TimeAgent 覆盖）：

| 动作类型 | 默认 TU |
|---|---|
| 快速扫视、聆听 | 1 |
| 对话、阅读、简单搜索 | 2-3 |
| 深度搜索、急救、潜行、力量对抗 | 4-6 |
| 移动场景 | 2-4 |

Entity 可在 `extra` 字段中覆盖：

```json
{"id": "I7", "extra": {"time_cost": 5}}
```

**advance_time 方法：**

```python
def advance_time(self, action_type: str, entity: Entity = None):
    cost = entity.extra.get("time_cost") if entity and entity.extra else None
    if cost is None:
        cost = DEFAULT_TIME_COST.get(action_type, 2)
    self.game_time += cost
    # 如果 TimeAgent 输出中有 time_of_day 变更，在此应用
```

### 引导层：TimeAgent（LLM sub-agent）

不对每个动作调用。只在以下时机触发（平均每 2-3 回合一次）：

- 进入新场景
- 完成了一个有 `time_cost` 的 entity
- 距上次调用已过 3+ 个 entity 处理
- 某个 countdown 接近 urgency 阈值

```python
class TimeAgent:
    """LLM sub-agent for time narrative guidance. Not a counter."""

    def assess(self, world, countdowns, scene_ctx, last_actions) -> dict:
        """
        输入: 当前世界状态、L3 countdown 配置、场景上下文、最近行动记录
        输出:
          time_delta: int            # 本次额外推进的时间单位（叠加到默认 cost 之上）
          time_of_day: str           # 当前时段，是否发生了变化
          countdown_updates: dict    # {cd_id: new_urgency}
          time_flags: dict           # 写入 runtime_state: {"time_night": True, ...}
          narrative_hint: str        # 注入 prompt 的时间上下文
          scene_desc_hint: str|None  # 场景描述是否需要调整（供 Narrator 使用）
        """
```

**调用参数：**

- 模型：`deepseek-v4-flash`
- thinking: disabled
- temperature: 0.3
- max_tokens: 500

**Prompt 结构：**

```
你是 TRPG 时间叙事引导者。基于模组时间配置和当前游戏状态，评估时间推进的节奏和叙事影响。

【模组时间配置】
{countdowns}

【当前世界状态】
  累计时间：{game_time} TU
  当前时段：{time_of_day}
  当前场景：{location}

【最近行动】
{last_actions}

【场景上下文】
{scene_context}

评估要点：
- 这个模组的时间性格是什么（紧迫/调查/昼夜循环/里程碑/混合）？
- 玩家刚刚的动作消耗了多少时间？节奏需要加速还是减速？
- 有没有 countdown 需要推进？urgency 应该升多少？
- 时间变化是否影响场景氛围或实体可见性？
- 输出 narrative_hint 供 Narrator 使用，应具体而非泛泛

返回 JSON。
```

---

## L3 Countdown 配置

0-3 个，定义模组的时间性格和宏观约束。不是具体触发点，而是给 TimeAgent 的导航坐标。

```json
"countdowns": [{
  "id": "CD1",
  "name": "吞噬逼近",
  "type": "urgency",
  "description": "后方巨嘴持续吞噬车厢。停留越久、探索越深，越是危险。",
  "trigger_condition": "进入5号车厢之后",
  "max_urgency": 10,
  "curve": "accelerating",
  "on_max": "E3" 
}]
```

### countdown type 枚举

| type | 含义 | 适合模组 |
|---|---|---|
| `urgency` | 拖延有代价，越拖越危险 | 常暗之厢、逃生型 |
| `investigation` | 调查推进解锁新时间窗口 | 侦探/悬疑型 |
| `cycle` | 昼夜（或更大）循环 | 哥特恐怖、沙盒型 |
| `milestone` | 关键事件触发时间跃迁 | 线性叙事型 |
| `countdown` | 严格截止，不可逆转 | 限时救援型 |

### 字段说明

| 字段 | 说明 |
|---|---|
| `id` | 唯一标识，供 entity requirement 引用 |
| `name` | 显示名称 |
| `type` | 上述枚举之一 |
| `description` | 自然语言描述，给 TimeAgent 做上下文 |
| `trigger_condition` | 自然语言，TimeAgent 判断何时激活 |
| `max_urgency` | urgency 上限（1-10），仅 urgency/countdown 类型使用 |
| `curve` | `linear` / `accelerating` / `decelerating`，影响 TimeAgent 的推进速度判断 |
| `on_max` | 可选，触发事件 ID 或 entity ID |
| `phases` | 仅 cycle 类型：`["day", "night"]` 或 `["dawn", "noon", "dusk", "midnight"]` |

---

## Entity 时间门控

三种方式，互补使用：

### 1. extra 字段（精确控制）

```json
{
  "id": "I_SHADOW",
  "name": "发现阴影中的狼人身影",
  "requirement": "",
  "extra": {
    "time_cost": 3,
    "time_gated": "night_only",
    "time_gated_desc": "只有在夜晚才能看到"
  }
}
```

`time_gated` 值：`night_only` / `day_only` / `countdown_cd1:3+` 等。由 TimeAgent 写入对应 `runtime_state` flag，Judge 的 requirement 解析自动处理。

### 2. requirement 字段（时间条件）

```json
{
  "id": "AT_PANIC",
  "name": "车厢开始崩裂",
  "requirement": "time_night AND countdown_cd1 >= 3"
}
```

`time_night`、`countdown_cd1 >= 3` → TimeAgent 将这些表达式写入 runtime_state 作为虚拟 entity state。`parse_hard_requirement` 已有 AND/OR 解析能力。

### 3. 提示展示（软引导）

Parse prompt 中 entity 的 `条件=` 字段展示 `time_gated_desc` 或时间条件，让 LLM 在意图匹配阶段就考虑时间因素。

---

## 场景描述时间变化

不走预定义版本。两层机制：

### 运行时注入

TimeAgent 的 `narrative_hint` 和 `scene_desc_hint` 注入到各 prompt：
- **Parse**：`【时间感知】{time_context}`
- **Enrich**：同上
- **Narrator**：`【时间感知】{time_context} + {scene_desc_hint}`

Narrator 基于这些上下文自然生成时间相关的描述。不需要预生成场景版本。

### 时间触发 AT + scene_update

当时间条件满足时（如 countdown urgency 达到阈值），对应的 AT 自动触发，其 side_effects 调用 `build_action_world_update` 或 `build_event_world_update` 更新场景描述。现有机制完全覆盖。

---

## 完整运行时流程

```
动作执行 → Judge advance_time(entity)
    ↓
TimeAgent 触发条件判断
    ↓ (满足触发条件)
TimeAgent.assess() → {
  time_delta, time_of_day, countdown_updates,
  time_flags, narrative_hint, scene_desc_hint
}
    ↓
更新 runtime_state[time_flags] + world.time_context
    ↓
后续 prompt 注入时间上下文
    ↓
Parse/Enrich/Narrator 基于时间上下文工作
    ↓
时间触发的 AT (requirement 含时间条件) 自动生效
```

---

## 跨模组迁移

| 模组类型 | 时间配置 | TimeAgent 行为 |
|---|---|---|
| 逃生型（常暗之厢） | 1 个 urgency countdown | 持续推进，氛围紧张 |
| 侦探型 | 1 个 investigation countdown | 调查深入后推进时间，解锁新线索 |
| 哥特恐怖 | 1 个 cycle countdown | 管理昼夜切换，触发不同 entity 集合 |
| 沙盒探索 | 无 countdown | 纯叙事节奏引导，fallback 默认 time_cost |
| 限时救援 | 1 个 countdown countdown | 严格倒计时 |
| 混合型 | 2-3 个不同类型的 countdown | TimeAgent 协调多时间维度 |

---

## 实现范围

### 新增文件

| 文件 | 内容 |
|---|---|
| `src/game/agents/time_agent.py` | `TimeAgent` 类（LLM sub-agent） |
| `docs/superpowers/specs/2026-05-19-time-system-design.md` | 本文档 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `scenario_core.py` | ScenarioWorld 加 `game_time`、`time_of_day`、`time_context`；加 `advance_time()` 方法；加 `DEFAULT_TIME_COST` 常量 |
| `game/judge.py` | `_execute_entity` 成功后调 `world.advance_time()`；requirement 解析支持 `time_*` 和 `countdown_*` 条件 |
| `game/agents/keeper.py` | `process_turn` 中集成 TimeAgent；prompt 调用处注入 `world.time_context` |
| `prompts.py` | Parse/Enrich/Narrator prompt 加入 `【时间感知】` 段；`_build_entity_lines` 适配 `time_gated` 显示 |
| L3 JSON schema | `l3_designer.py` 数据类加 `Countdown`；pipeline 输出格式加 `countdowns` |

### 不改动

- `src/llm.py` — 现有 sub-agent 模式直接复用
- L2 entity 必需字段 — `time_cost` 和 `time_gated` 在 `extra` 中可选
- Pipeline 核心流程 — countdown 是 L3 可选的补充字段

---

## 开放问题

1. **TimeAgent 触发频率的具体阈值** — 需要实际游玩测试确定最佳平衡点
2. **`time_of_day` 转换逻辑** — 是否由 TimeAgent 全权决定，还是部分通过 game_time 推算
3. **countdown urgency 到 entity 触发** — 当前方案通过 AT 的 requirement 引用，是否还需要更直接的绑定
4. **多玩家/同伴的时间感知** — 不同玩家可能在不同场景，时间如何协调
