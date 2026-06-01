# src/investigator/__init__.py
"""COC 7th 调查员车卡系统"""

from investigator.models import (
    Stats,
    DerivedStats,
    Skill,
    Occupation,
    Weapon,
    Investigator,
)

# Serialization — available after Task 4
try:
    from investigator.serialization import (
        to_json, from_json, to_dict, from_dict,
    )
    _HAS_SERIALIZATION = True
except ImportError:
    _HAS_SERIALIZATION = False

# 便捷函数：从 JSON 文件直接加载 Investigator
load_investigator = from_json if _HAS_SERIALIZATION else None  # type: ignore

__all__ = [
    "Stats",
    "DerivedStats",
    "Skill",
    "Occupation",
    "Weapon",
    "Investigator",
]

if _HAS_SERIALIZATION:
    __all__.extend(["to_json", "from_json", "to_dict", "from_dict", "load_investigator"])
