"""
LLM 后端配置模板。
复制为 config_llm.py 并填入你自己的配置。
config_llm.py 不会被 Git 跟踪。
"""

# ═══════════════════════════════════════════════════════════════
# API 连接
# ═══════════════════════════════════════════════════════════════

LLM_BASE_URL = "https://api.deepseek.com"
"""API 端点 URL。支持任何 DeepSeek 兼容 API（OpenRouter、vLLM 等）。"""

LLM_API_KEY_ENV = "DEEPSEEK_API_KEY"
"""API Key 环境变量名。从 .env 文件或系统环境读取。"""


# ═══════════════════════════════════════════════════════════════
# 模型选择
# ═══════════════════════════════════════════════════════════════

LLM_DEFAULT_MODEL = "deepseek-v4-pro"
"""主模型：用于 Keeper Parse、Narrator、Author 等核心调用。"""

LLM_FLASH_MODEL = "deepseek-v4-flash"
"""轻量模型：用于 CombatEntry、TimeAgent、Enrich、Standoff 等高频调用。"""


# ═══════════════════════════════════════════════════════════════
# 生成参数默认值
# ═══════════════════════════════════════════════════════════════

LLM_THINKING_ENABLED = True
"""是否启用思考模式（deepseek reasoning）。"""

LLM_REASONING_EFFORT = "high"
"""推理强度："low" / "medium" / "high" / "max"。"""

LLM_TEMPERATURE_JSON = 0.3
"""JSON 模式（结构化判定）默认温度。"""

LLM_TEMPERATURE_TEXT = 0.7
"""文本模式（叙事生成）默认温度。"""

LLM_MAX_TOKENS_JSON = 162840
"""JSON 模式默认 max_tokens。"""

LLM_MAX_TOKENS_TEXT = 20000
"""文本模式默认 max_tokens。"""


# ═══════════════════════════════════════════════════════════════
# 各调用点的 reasoning_effort 覆盖
# ═══════════════════════════════════════════════════════════════

RE_KEEPER_PARSE = "max"
RE_NARRATOR = "max"
RE_COMBAT_ENTRY = "low"
RE_TIME_AGENT = None           # None = 使用 LLM_REASONING_EFFORT 默认值
RE_AUTHOR = "max"
RE_INTENT_DETECTOR = "low"
RE_ENRICH = None
RE_STANDOFF = None
RE_MEMORY_COMPRESS = None
RE_COMBAT_NARRATIVE = "low"
RE_SUPPLEMENT_NARRATIVE = "max"
RE_SUPPLEMENT_ENTITIES = "max"
RE_SUPPLEMENT_L1 = "max"
RE_SUPPLEMENT_L3 = "max"


# ═══════════════════════════════════════════════════════════════
# 未来扩展（远期，低优先级）
# ═══════════════════════════════════════════════════════════════
# 预留 LLM_PROVIDER 字段，未来支持多 provider 抽象：
# LLM_PROVIDER = "deepseek"  # "deepseek" | "openai" | "anthropic" | "openrouter"
