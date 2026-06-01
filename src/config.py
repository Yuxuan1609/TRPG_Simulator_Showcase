"""
集中化配置 —— 不包含 API 密钥等敏感信息。
所有硬编码的开关、阈值、魔法数字统一从此读取。
"""

# ═══════════════════════════════════════════════════════════════
# 子系统开关
# ═══════════════════════════════════════════════════════════════

WR0_ENABLED = False
"""创作者豁免（World Rule 0）。开启后 Author 不受世界规则约束。"""

OFFLINE_INJECTION_ENABLED = True
"""模组构建时离线预填充武器/敌人。"""

RUNTIME_INJECTION_ENABLED = True
"""游戏运行时动态注入武器/敌人（/inject 命令）。"""

JUDGMENT_TIER2_ENABLED = True
"""LLM 增强技能判定（Tier 2）。关闭后仅用确定性 D100 判定。"""

SHOW_NON_TRIGGERABLE = True
"""Keeper Parse prompt 是否展示未满足条件的实体。"""

SHOW_COMPLETED = False
"""Keeper Parse prompt 是否展示已完成的实体。默认关闭，已完成实体从可触发列表中移除。"""


INJECT_L3_WR0 = True
"""管线是否向 L3 的 world_rules 注入 WR0 条目。"""

COMBAT_LLM_ENHANCEMENT = False
"""战斗系统 LLM 增强开关（预留）。开启后每轮战斗叙事由 LLM 生成，
战斗总结由 LLM 汇总（调用 build_combat_narrative_prompt）。
当前仅影响战斗叙事输出管线，不影响战斗机制本身。"""


# ═══════════════════════════════════════════════════════════════
# 管线监控（U5）
# ═══════════════════════════════════════════════════════════════

MONITOR_ENABLED = True
"""监控总开关。False 时 LLMSensor 零开销跳过所有记录。"""

MONITOR_HISTORY_SIZE = 200
"""LLMSensor 环形缓冲最大记录数。"""

# ── 降级阈值 ──

LLM_SLOW_THRESHOLD_MS = 8000
"""LLM 调用慢阈值（毫秒）。超过此阈值的调用记录 slow。"""

LLM_TIMEOUT_MS = 45000
"""LLM 调用超时阈值（毫秒）。超时后触发 on_timeout 降级。"""

LLM_MAX_CONSECUTIVE_FAILURES = 3
"""连续失败次数阈值。达到后触发 on_consecutive_failures 降级。"""

LLM_DEGRADE_RECOVERY_COUNT = 5
"""降级后恢复所需连续成功次数。"""

LLM_SLOW_RATE_THRESHOLD = 0.5
"""近 10 次慢调用比例阈值。超过后预防性降级。"""

# ── 降级策略集中化配置 ──

DEGRADE_POLICY: dict[str, dict] = {
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
        "reject_all_structural": True,
    },
    "time_agent": {
        "skip": True,
    },
    "intent_detector": {
        "default_result": True,
    },
}
"""每个 Agent 的降级行为参数。DegradationPolicy 实现类在 init 时读取。"""


# ═══════════════════════════════════════════════════════════════
# 游戏循环阈值
# ═══════════════════════════════════════════════════════════════

MAX_ESCALATION_DEPTH = 3
"""Author Patch/StructuralEdit 递归深度上限。"""

INTENT_COOLDOWN_WINDOW = 3
"""IntentDetector 相同意图去重窗口（回合数）。"""

COMMS_INTERVAL_MINUTES = 15
"""TimePressure 通信间隔（游戏内分钟数）。"""

NPC_MEMORY_CAP = 20
"""NPC 对话记忆条数上限。"""


# ═══════════════════════════════════════════════════════════════
# 管线参数
# ═══════════════════════════════════════════════════════════════

PIPELINE_MAX_RETRIES = 3
"""管线 LLM 调用最大重试次数。"""


# ═══════════════════════════════════════════════════════════════
# Agent 系统提示词覆盖（可选）
# ═══════════════════════════════════════════════════════════════
# 留空字符串则使用 agent 内置默认值。
# 提供非空字符串则完全替换对应 agent 的 system prompt。

AGENT_SYSTEM_PROMPTS = {
    "keeper_parse": "",
    "keeper_enrich": "",
    "narrator": "",
    "combat_entry": "",
    "time_agent": "",
    "author": "",
    "author_time_pressure": "",
    "intent_detector": "",
    "npc_dialogue": "",
    "trait_enhance": "",
    "failure_penalty": "",
    "memory_compress": "",
}


# ═══════════════════════════════════════════════════════════════
# TurnMonitor 管线状态机
# ═══════════════════════════════════════════════════════════════

TURN_STEP_MAX_RETRIES = 2
"""管线段默认最大重试次数。"""

# ═══════════════════════════════════════════════════════════════
# 自动存档
# ═══════════════════════════════════════════════════════════════

AUTOSAVE_ENABLED = True
AUTOSAVE_INTERVAL_SEC = 600       # 10 分钟
AUTOSAVE_MAX_COPIES = 5
AUTOSAVE_DIR = "data/autosave"
