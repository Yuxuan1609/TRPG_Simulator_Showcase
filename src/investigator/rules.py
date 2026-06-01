# src/investigator/rules.py
"""COC 7th 规则引擎 —— 全部为纯函数"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple, Optional

from utils import roll_d6, roll_dice
from investigator.models import Stats, DerivedStats, Skill, Occupation, Weapon


# ═══════════════════════════════════════════════════════════════
#  属性生成
# ═══════════════════════════════════════════════════════════════

def roll_stats() -> Stats:
    """按 COC 7th 标准规则掷骰生成核心属性"""
    return Stats(
        STR=roll_d6(3) * 5,
        CON=roll_d6(3) * 5,
        SIZ=(roll_d6(2) + 6) * 5,
        DEX=roll_d6(3) * 5,
        APP=roll_d6(3) * 5,
        INT=(roll_d6(2) + 6) * 5,
        POW=roll_d6(3) * 5,
        EDU=(roll_d6(2) + 6) * 5,
        LUCK=roll_d6(3) * 5,
    )


# ═══════════════════════════════════════════════════════════════
#  衍生属性计算
# ═══════════════════════════════════════════════════════════════

def _calc_db_build(str_siz: int) -> Tuple[str, int]:
    """根据 STR+SIZ 查表返回 (DB, BUILD)"""
    if str_siz <= 64:
        return "-2", -2
    elif str_siz <= 84:
        return "-1", -1
    elif str_siz <= 124:
        return "0", 0
    elif str_siz <= 164:
        return "+1D4", 1
    elif str_siz <= 204:
        return "+1D6", 2
    else:
        return "+2D6", 3


def calc_derived(stats: Stats, age: int = 20, cthulhu_mythos: int = 0) -> DerivedStats:
    """根据核心属性 + 年龄 + 克苏鲁神话计算衍生属性"""
    hp = math.floor((stats.CON + stats.SIZ) / 10)
    mp = math.floor(stats.POW / 5)
    san = stats.POW
    san_max = 99 - cthulhu_mythos
    dodge = math.floor(stats.DEX / 2)

    # MOV
    if stats.STR < stats.SIZ and stats.DEX < stats.SIZ:
        mov = 7
    elif stats.STR > stats.SIZ and stats.DEX > stats.SIZ:
        mov = 9
    else:
        mov = 8

    db, build = _calc_db_build(stats.STR + stats.SIZ)

    return DerivedStats(
        HP=hp, HP_MAX=hp, MP=mp, SAN=san, SAN_MAX=san_max,
        MOV=mov, DB=db, BUILD=build, DODGE=dodge,
    )


# ═══════════════════════════════════════════════════════════════
#  技能系统
# ═══════════════════════════════════════════════════════════════

# COC 7th 标准技能基础值表
SKILL_BASE_VALUES: Dict[str, int] = {
    "会计": 5, "人类学": 1, "估价": 5, "考古学": 1,
    "魅惑": 15, "攀爬": 20, "计算机使用": 5, "信用评级": 0,
    "克苏鲁神话": 0, "乔装": 5, "汽车驾驶": 20,
    "电气维修": 10, "电子学": 1, "话术": 5, "格斗": 25,
    "枪械": 20, "急救": 30, "历史": 5, "恐吓": 15,
    "跳跃": 20, "外语": 1, "母语": 50, "法律": 5,
    "图书馆使用": 20, "聆听": 20, "锁匠": 1, "机械维修": 10,
    "医学": 1, "博物学": 10, "导航": 10, "神秘学": 5,
    "操作重型机械": 1, "说服": 10, "驾驶": 20, "心理学": 10,
    "精神分析": 1, "骑术": 5, "科学": 1, "妙手": 10,
    "潜行": 20, "侦查": 25, "生存": 10, "游泳": 20,
    "投掷": 20, "追踪": 10,
}

# 技能分类映射
SKILL_CATEGORIES: Dict[str, str] = {
    "会计": "知识", "人类学": "知识", "估价": "知识", "考古学": "知识",
    "魅惑": "社交", "攀爬": "操作", "计算机使用": "知识", "信用评级": "社交",
    "克苏鲁神话": "知识", "乔装": "社交", "汽车驾驶": "操作",
    "电气维修": "操作", "电子学": "知识", "话术": "社交", "格斗": "战斗",
    "枪械": "战斗", "急救": "操作", "历史": "知识", "恐吓": "社交",
    "跳跃": "操作", "外语": "知识", "母语": "知识", "法律": "知识",
    "图书馆使用": "知识", "聆听": "感知", "锁匠": "操作", "机械维修": "操作",
    "医学": "知识", "博物学": "知识", "导航": "知识", "神秘学": "知识",
    "操作重型机械": "操作", "说服": "社交", "驾驶": "操作", "心理学": "感知",
    "精神分析": "知识", "骑术": "操作", "科学": "知识", "妙手": "操作",
    "潜行": "操作", "侦查": "感知", "生存": "操作", "游泳": "操作",
    "投掷": "战斗", "追踪": "感知",
}


def resolve_base_value(base: int, stats: Optional[Stats] = None) -> int:
    """解析技能基础值。int 直接返回（特殊值如 'DEX/2' 已在表中直接以数值存储）"""
    return base


def create_skill_list() -> List[Skill]:
    """从基础值表生成完整技能列表"""
    skills = []
    for name, base in SKILL_BASE_VALUES.items():
        category = SKILL_CATEGORIES.get(name, "通用")
        skills.append(Skill(
            name=name,
            base_value=base,
            value=base,
            category=category,
        ))
    return skills


def allocate_skill_points(
    skills: List[Skill],
    occupation_skills: List[str],
    occupation_points: int,
    interest_points: int,
) -> List[Skill]:
    """
    分配技能点（自动平均分配）。
    - occupation_points: 职业技能点，仅可分配到职业技能
    - interest_points: 兴趣技能点，可分配到任意技能
    返回更新后的技能列表（原位修改）。
    """
    occ_skills = [s for s in skills if s.name in occupation_skills]
    int_skills = [s for s in skills if s.name not in occupation_skills]

    if occ_skills:
        per_occ = occupation_points // len(occ_skills)
        remainder = occupation_points % len(occ_skills)
        for i, sk in enumerate(occ_skills):
            sk.value = min(99, sk.base_value + per_occ + (1 if i < remainder else 0))

    if int_skills:
        per_int = interest_points // len(int_skills)
        remainder = interest_points % len(int_skills)
        for i, sk in enumerate(int_skills):
            sk.value = min(99, sk.base_value + per_int + (1 if i < remainder else 0))

    return skills


def calc_occupation_points(formula: str, stats: Stats) -> int:
    """根据职业公式计算职业技能点数。e.g. 'EDU*4' → stats.EDU * 4"""
    try:
        result = 0
        parts = formula.replace("-", "+-").split("+")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if "*" in part:
                attr, mul = part.split("*")
                attr = attr.strip().upper()
                mul = int(mul.strip())
                result += getattr(stats, attr, 0) * mul
            else:
                attr = part.strip().upper()
                if hasattr(stats, attr):
                    result += getattr(stats, attr)
        return result
    except Exception:
        return stats.EDU * 4  # fallback


# ═══════════════════════════════════════════════════════════════
#  年龄修正
# ═══════════════════════════════════════════════════════════════

def apply_age_modifiers(stats: Stats, age: int):
    """
    COC 7th 年龄修正（原位修改）。

    | 年龄段 (tier) | APP    | STR/CON/DEX   | EDU  |
    |---------------|--------|---------------|------|
    | 40-49 (0)     | -5     | 0             | +5   |
    | 50-59 (1)     | -10    | -5            | +10  |
    | 60-69 (2)     | -15    | -10           | +15  |
    | 70-79 (3)     | -20    | -20           | +20  |
    | 80+ (4)       | -25    | -40           | +25  |
    """
    if age < 40:
        return

    tier = (age - 40) // 10
    if tier > 4:
        tier = 4

    # Lookup tables by tier
    app_penalties = [-5, -10, -15, -20, -25]
    phys_penalties = [0, -5, -10, -20, -40]
    edu_bonuses = [5, 10, 15, 20, 25]

    stats.APP = max(0, stats.APP + app_penalties[tier])
    if phys_penalties[tier]:
        stats.STR = max(0, stats.STR + phys_penalties[tier])
        stats.CON = max(0, stats.CON + phys_penalties[tier])
        stats.DEX = max(0, stats.DEX + phys_penalties[tier])
    stats.EDU = min(99, stats.EDU + edu_bonuses[tier])


# ═══════════════════════════════════════════════════════════════
#  信用评级
# ═══════════════════════════════════════════════════════════════

CREDIT_RATING_TABLE: Dict[int, str] = {
    0: "身无分文",
    5: "拮据",
    10: "一般",
    20: "中等",
    30: "宽裕",
    50: "富裕",
    70: "富有",
    90: "极富",
}


def get_credit_level(value: int) -> str:
    """根据信用评级数值返回等级描述"""
    result = "身无分文"
    for threshold, label in sorted(CREDIT_RATING_TABLE.items()):
        if value >= threshold:
            result = label
    return result


# ═══════════════════════════════════════════════════════════════
#  战斗
# ═══════════════════════════════════════════════════════════════

def create_default_unarmed() -> Weapon:
    """创建默认徒手攻击武器"""
    return Weapon(
        name="徒手",
        skill_name="格斗",
        damage="1D3+DB",
        range="接触",
    )


def create_default_dodge_skill(stats: Stats) -> Skill:
    """创建闪避技能（基础值 = DEX/2）"""
    dodge_base = math.floor(stats.DEX / 2)
    return Skill(
        name="闪避",
        base_value=dodge_base,
        value=dodge_base,
        category="战斗",
    )


# ═══════════════════════════════════════════════════════════════
#  职业加载
# ═══════════════════════════════════════════════════════════════

def load_occupations(path: str) -> List[Occupation]:
    """从 JSON 文件加载职业列表"""
    import json
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return [
        Occupation(
            name=d["name"],
            description=d.get("description", ""),
            occupation_skills=d.get("occupation_skills", []),
            credit_rating_min=d.get("credit_rating_min", 0),
            credit_rating_max=d.get("credit_rating_max", 99),
            skill_points_formula=d.get("skill_points_formula", "EDU*4"),
        )
        for d in data
    ]


def calc_db(STR: int, SIZ: int) -> str:
    """COC 7th Damage Bonus from STR + SIZ."""
    total = STR + SIZ
    if total <= 64:
        return "-2"
    if total <= 84:
        return "-1"
    if total <= 124:
        return "0"
    if total <= 164:
        return "+1D4"
    return "+1D6"
