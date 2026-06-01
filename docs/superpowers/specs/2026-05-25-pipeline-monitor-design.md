# PipelineMonitor — 管线运行时监控设计

日期: 2026-05-25

## 1. 概述

在现有 `call_deepseek()` 统一入口和 `config.py` 预留阈值基础上，构建两层监控架构：

- **Layer 1 — LLMSensor（传感器）**：嵌入 `call_deepseek`，零侵入记录每次调用
- **Layer 2 — AgentMonitor（决策层）**：每 Agent 持一个 monitor，自定义降级策略
- **PipelineHealth（全局聚合）**：跨 Agent 可观测性出口

## 2. LLMSensor（Layer 1）

### 2.1 数据模型

```python
@dataclass
class LLMCallRecord:
    timestamp: float           # time.time()
    label: str                 # "Keeper Parse" / "Narrator" / etc.
    model: str                 # "deepseek-v4-pro" / "deepseek-v4-flash"
    json_mode: bool
    duration_ms: float
    http_status: int
    ok: bool                   # 含 JSON 有效性
    json_valid: bool | None    # json_mode 专属
    response_len: int
    tokens_used: int | None
```

### 2.2 挂载方式

`call_deepseek()` 内部，函数头尾加 timing + 记录。对调用方完全透明。

```python
_sensor: LLMSensor | None = None  # 全局单例

def call_deepseek(prompt, *, json_mode=True, ...):
    t0 = time.time()
    try:
        response = _raw_call(...)
    except Exception:
        if _sensor:
            _sensor.record(..., ok=False, ...)
        raise
    duration = (time.time() - t0) * 1000
    if _sensor:
        json_ok = json_mode 且解析成功
        _sensor.record(label=_current_log_label, model=model,
                       duration_ms=duration, ok=json_ok, ...)
```

- `enabled=False` → 跳过所有记录，零开销
- `label` 复用现有 `_current_log_label`
- `history`：最近 200 条环形缓冲
- 统计按 label prefix 聚合到 agent（`Keeper` / `Narrator` / `Author` / `Pipeline`）

### 2.3 聚合统计

```python
@dataclass
class AgentStats:
    agent_name: str
    total_calls: int
    total_failures: int
    total_slow_calls: int     # duration > LLM_SLOW_THRESHOLD_MS
    avg_duration_ms: float
    failure_rate: float       # 最近 20 次
    slow_rate: float          # 最近 20 次
```

## 3. AgentMonitor（Layer 2）

### 3.1 接口

```python
class AgentMonitor:
    def __init__(self, agent_name: str, sensor: LLMSensor,
                 policy: DegradationPolicy, config: MonitorConfig):
        ...

    def call(self, prompt, **kwargs) -> dict | str:
        """包装 call_deepseek，自动记录 + 降级决策"""
        ...

    @property
    def degraded(self) -> bool
    @property  
    def stats(self) -> AgentStats
```

### 3.2 降级触发

| 条件 | 阈值 | 动作 |
|------|------|------|
| 单次超时 | `duration > LLM_TIMEOUT_MS` | `policy.on_timeout()` → 重试 1 次 |
| 连续失败 | `_consecutive_failures >= 3` | `policy.on_consecutive_failures()` → 切模型 |
| 慢调用率 | 近 10 次 >50% 超 `LLM_SLOW_THRESHOLD_MS` | 预防性降级 → `policy.on_degrade()` |

恢复：连续 5 次成功且延迟正常 → `_degraded=False`。

### 3.3 DegradationPolicy（接口化 + 集中化配置）

```python
class DegradationPolicy(Protocol):
    """每个 Agent 自定义降级行为，参数从 DEGRADE_POLICY 读取"""
    def __init__(self, config: dict): ...
    def on_timeout(self, call_record: LLMCallRecord, kwargs: dict) -> RetryAction | None: ...
    def on_consecutive_failures(self, count: int) -> str | None: ...
    def on_degrade(self) -> dict: ...
```

各 Agent 默认策略（行为参数在 `config.py:DEGRADE_POLICY`）：

| Agent | on_degrade 行为 |
|-------|----------------|
| Keeper | `DEGRADE_POLICY["keeper"]` → 跳过 enrich/combat_entry/intent_detect |
| Narrator | `DEGRADE_POLICY["narrator"]` → 切 flash，关 thinking |
| Author | `DEGRADE_POLICY["author"]` → 拒绝所有 structural edit |
| TimeAgent | `DEGRADE_POLICY["time_agent"]` → 直接跳过 |
| IntentDetector | `DEGRADE_POLICY["intent_detector"]` → fail-open 默认有意图 |

所有阈值、模型选择、行为开关均在 `config.py` 一处管理，策略类只读不写。

### 3.4 使用方式

```python
class Keeper:
    def __init__(self, ...):
        self.monitor = AgentMonitor("Keeper", sensor=llm._sensor,
                                     policy=KeeperDegradation(), config=monitor_config)

    def _parse(self, raw):
        return self.monitor.call(prompt, json_mode=True, ...)
        # 替代直接 call_deepseek(prompt, json_mode=True, ...)
```

## 4. PipelineHealth（全局聚合）

```python
class PipelineHealth:
    """跨 Agent 只读聚合，不参与降级决策"""
    def snapshot(self) -> dict:
        return {
            "uptime_seconds": ...,
            "total_calls": ...,
            "total_failures": ...,
            "agents": {
                "Keeper": {"degraded": False, "calls": 42, "failures": 1, ...},
                "Narrator": {...},
                ...
            }
        }
```

出口：
- `logs/<ts>/health.json` — 每轮结束写入
- CLI `/health` — 实时查询（已有调试命令体系）

## 5. 配置

### 5.1 config.py — 集中化参数

```python
# ── 监控通用 ──
MONITOR_ENABLED = True           # 传感器总开关
MONITOR_HISTORY_SIZE = 200       # LLMSensor 环形缓冲大小

# ── 降级阈值 ──
LLM_SLOW_THRESHOLD_MS = 8000     # 慢调用警告阈值
LLM_TIMEOUT_MS = 45000           # 单次超时阈值
LLM_MAX_CONSECUTIVE_FAILURES = 3 # 连续失败触发降级
LLM_DEGRADE_RECOVERY_COUNT = 5   # 恢复所需连续成功次数
LLM_SLOW_RATE_THRESHOLD = 0.5    # 近 10 次慢调用比例阈值

# ── 降级策略集中化配置 ──
# 每个 Agent 的降级行为参数，聚焦于可配置项
DEGRADE_POLICY = {
    "keeper": {
        "fallback_model": "deepseek-v4-flash",
        "skip_enrich": True,
        "skip_combat_entry": True,
        "skip_intent_detect": True,
    },
    "narrator": {
        "fallback_model": "deepseek-v4-flash",
        "thinking": False,
        "reasoning_effort": "low",
    },
    "author": {
        "fallback_model": "deepseek-v4-flash",
        "reject_all_structural": True,   # 拒绝所有 structural edit
    },
    "time_agent": {
        "skip": True,                     # TimeAgent 降级直接跳过
    },
    "intent_detector": {
        "default_result": True,           # 默认认为有对话意图（fail-open）
    },
}
```

`DegradationPolicy` 实现类在初始化时读取 `DEGRADE_POLICY`，不硬编码参数。

## 6. 文件结构

- `src/monitor/__init__.py` — 公开 API
- `src/monitor/sensor.py` — LLMSensor + LLMCallRecord + AgentStats
- `src/monitor/agent_monitor.py` — AgentMonitor + DegradationPolicy
- `src/monitor/health.py` — PipelineHealth 单例
- `src/monitor/policies.py` — Keeper/Narrator/Author/TimeAgent 降级策略默认实现
- `src/llm.py` — 加 `_sensor` 全局变量 + record 埋点（~15 行改动）
- `src/config.py` — 补充 `MONITOR_ENABLED` / `MONITOR_HISTORY_SIZE` / `MONITOR_DEGRADE_RECOVERY`

## 7. 各 Agent 接入点

| Agent | 调用点 | 替换为 monitor.call() |
|-------|-------|----------------------|
| Keeper | `_parse()` | ✓ |
| Keeper | `_enrich()` | ✓ |
| Keeper | `combat_entry` LLM 判定 | ✓ |
| Keeper | `standoff_match` LLM | ✓ |
| Keeper | `_inject_npc_at()` 内的 intent detect | ✓ |
| Narrator | `narrate()` | ✓ |
| Author | `handle_request()` | ✓ |
| TimeAgent | `assess()` | ✓ |
| IntentDetector | `detect()` | ✓ |

## 8. 测试策略

| 层级 | 内容 |
|------|------|
| LLMSensor 单元 | record 写入、环形缓冲、统计聚合 |
| AgentMonitor 单元 | mock sensor — 降级触发/恢复、policy 调用 |
| DegradationPolicy 单元 | 各 Agent 策略返回值正确性 |
| PipelineHealth 集成 | snapshot 正确性、/health CLI |
| E2E | mock LLM 连续失败 → 验证 Keeper 跳过 enrich 直接 curator |
