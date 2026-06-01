# src/investigator/models.py
"""COC 7th 调查员数据模型"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


@dataclass
class Stats:
    """八项核心属性 + LUCK（COC 7th）"""
    STR: int = 0   # 力量   (3D6*5)
    CON: int = 0   # 体质   (3D6*5)
    SIZ: int = 0   # 体型   (2D6+6)*5
    DEX: int = 0   # 敏捷   (3D6*5)
    APP: int = 0   # 外貌   (3D6*5)
    INT: int = 0   # 智力   (2D6+6)*5
    POW: int = 0   # 意志   (3D6*5)
    EDU: int = 0   # 教育   (2D6+6)*5
    LUCK: int = 0  # 幸运   (3D6*5)


@dataclass
class DerivedStats:
    """衍生属性（从核心属性计算得出）"""
    HP: int = 0          # 当前生命值
    HP_MAX: int = 0      # 最大生命值 = floor((CON+SIZ)/10)
    MP: int = 0          # 魔法值 = floor(POW/5)
    SAN: int = 0         # 当前理智 = POW (初始)
    SAN_MAX: int = 99    # 最大理智 = 99 - 克苏鲁神话值
    MOV: int = 8         # 移动力 (7/8/9)
    DB: str = "0"        # 伤害加值
    BUILD: int = 0       # 体格
    DODGE: int = 0       # 闪避 = floor(DEX/2)


@dataclass
class Skill:
    """COC 7th 技能"""
    name: str
    base_value: int
    value: int = 0           # 当前值（初始 = 基础值，分配技能点后增长）
    category: str = "通用"    # 战斗 / 社交 / 知识 / 感知 / 操作 / 通用
    is_occupation: bool = False

    def __post_init__(self):
        if self.value == 0:
            self.value = self.base_value


@dataclass
class Occupation:
    """COC 7th 职业定义"""
    name: str
    description: str
    occupation_skills: List[str] = field(default_factory=list)
    credit_rating_min: int = 0
    credit_rating_max: int = 99
    skill_points_formula: str = "EDU*4"  # e.g. "EDU*4", "EDU*2+DEX*2"


@dataclass
class Weapon:
    """武器"""
    name: str
    skill_name: str = "格斗"    # 关联技能名
    damage: str = "1D3+DB"     # 伤害公式
    range: str = "接触"         # 射程
    ammo: int = 0              # 弹药（0 表示不需要）
    malfunction: int = 100     # 故障值
    damage_type: str = "物理"
    armor_piercing: int = 0
    attack_bonus: int = 0
    multi_attack: int = 1
    special_rules: str = ""


@dataclass
class InventoryItem:
    """非武器/非剧情关键物品"""
    name: str
    description: str = ""
    quantity: int = 1
    category: str = "misc"  # tool, consumable, clothing, document, misc


class ItemManager:
    """半结构化物品管理器 — 持有非武器/剧情相关的常规物品"""

    def __init__(self):
        self._items: dict[str, InventoryItem] = {}

    def add(self, name: str, description: str = "", quantity: int = 1) -> InventoryItem:
        if name in self._items:
            self._items[name].quantity += quantity
            if description:
                self._items[name].description = description
            return self._items[name]
        item = InventoryItem(name=name, description=description, quantity=quantity)
        self._items[name] = item
        return item

    def remove(self, name: str, quantity: int = 1):
        if name in self._items:
            self._items[name].quantity -= quantity
            if self._items[name].quantity <= 0:
                del self._items[name]

    def has(self, name: str) -> bool:
        return name in self._items

    def get(self, name: str) -> InventoryItem | None:
        return self._items.get(name)

    def list_all(self) -> list[InventoryItem]:
        return list(self._items.values())

    def describe(self) -> str:
        """半结构化描述已持有物品"""
        if not self._items:
            return "（未持有物品）"
        lines = []
        for item in self._items.values():
            desc = f"- {item.name} x{item.quantity}"
            if item.description:
                desc += f"：{item.description}"
            lines.append(desc)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            name: {"description": item.description, "quantity": item.quantity, "category": item.category}
            for name, item in self._items.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ItemManager":
        mgr = cls()
        for name, idata in data.items():
            mgr.add(name, description=idata.get("description", ""),
                   quantity=idata.get("quantity", 1))
        return mgr


class Investigator:
    """COC 7th 调查员 —— 完全替代旧 Player 类"""

    _ALLOWED_STATS = {"STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"}

    def __init__(
        self,
        name: str = "Unknown",
        age: int = 20,
        gender: str = "",
        occupation: Optional[Occupation] = None,
        stats: Optional[Stats] = None,
        derived: Optional[DerivedStats] = None,
        skills: Optional[List[Skill]] = None,
        weapons: Optional[List[Weapon]] = None,
        equipment: Optional[List[str]] = None,   # deprecated, kept for serialization compat
        backstory: str = "",
        appearance: str = "",
        personal_description: str = "",
        avatar_url: str = "",       # optional avatar image URL
        extra: str = "",            # reserved for future trait/mechanic extensions
    ):
        self.name = name
        self.age = age
        self.gender = gender
        self.occupation = occupation

        self.stats = stats or Stats()
        self.derived = derived or DerivedStats()

        self.skills: List[Skill] = skills or []
        self.weapons: List[Weapon] = weapons or []
        self.equipment: List[str] = equipment or []
        self.item_manager: ItemManager = ItemManager()

        self.backstory = backstory
        self.appearance = appearance
        self.personal_description = personal_description
        self.avatar_url = avatar_url
        self.extra = extra

    # ── 兼容旧 Player 接口 ──

    @property
    def skills_dict(self) -> Dict[str, int]:
        """返回 {技能名: 当前值} 映射"""
        return {s.name: s.value for s in self.skills}

    # ── 查询 ──

    def get_skill(self, name: str) -> Optional[Skill]:
        for s in self.skills:
            if s.name == name:
                return s
        return None

    def get_skill_value(self, name: str) -> int:
        sk = self.get_skill(name)
        return sk.value if sk else 0

    # ── 技能检定（COC 7th D100 规则）──

    def check_skill(self, skill_name: str, difficulty: str = "regular") -> tuple[bool, str]:
        """
        COC 7th 技能检定：投掷 D100，结果 ≤ 技能值则为成功。

        difficulty:
          - "regular": 阈值 = 技能值
          - "hard":    阈值 = floor(技能值 / 2)
          - "extreme": 阈值 = floor(技能值 / 5)

        若调查员未拥有该技能，默认判定成功（避免缺少冷门技能卡关）。
        返回 (是否成功, 结果描述文本, 实际达成等级)。
        等级: "fumble" | "failure" | "regular" | "hard" | "extreme"
        """
        skill = self.get_skill(skill_name)
        if skill is None:
            return True, f"{skill_name}（未掌握，默认判定成功）", "regular"

        roll = random.randint(1, 100)

        # 大失败 (fumble): 96-100
        if roll >= 96:
            detail = f"{skill_name}检定：D100={roll}/{skill.value} ≥96 大失败！"
            return False, detail, "fumble"
        # 大成功 (critical): 1
        if roll == 1:
            detail = f"{skill_name}检定：D100=1/{skill.value} 大成功！"
            return True, detail, "extreme"

        # 按阈值确定等级
        extreme_threshold = max(1, skill.value // 5)
        hard_threshold = max(1, skill.value // 2)

        if roll <= extreme_threshold:
            tier = "extreme"
        elif roll <= hard_threshold:
            tier = "hard"
        elif roll <= skill.value:
            tier = "regular"
        else:
            detail = f"{skill_name}检定：D100={roll}/{skill.value} > 失败"
            return False, detail, "failure"

        detail = f"{skill_name}检定：D100={roll}/{skill.value} ≤ {skill.value} 成功（{tier}级）"
        return True, detail, tier

    def check_skills(self, skill_names: list[str]) -> tuple[bool, str, str]:
        """
        批量技能检定（AND 逻辑）。全部通过返回 (True, 合并结果文本, 最低达成等级)；
        任一失败返回 (False, 合并结果文本, "failure")。
        """
        results = []
        all_pass = True
        min_tier = "extreme"
        tier_rank = {"fumble": 0, "failure": 1, "regular": 2, "hard": 3, "extreme": 4}
        for name in skill_names:
            ok, msg, tier = self.check_skill(name)
            results.append(msg)
            if not ok:
                all_pass = False
            if tier_rank.get(tier, 99) < tier_rank.get(min_tier, 99):
                min_tier = tier
        return all_pass, "；".join(results), min_tier

    def build_snapshot(self) -> dict:
        """Return a lightweight dict of player state for prompt contexts."""
        return {
            "name": self.name,
            "hp": self.derived.HP,
            "max_hp": self.derived.HP_MAX,
            "san": self.derived.SAN,
            "mp": self.derived.MP,
            "weapons": [w.name for w in self.weapons],
            "inventory": self.item_manager.describe(),
            "skills_summary": ", ".join(
                f"{s.name}={s.value}" for s in self.skills[:10]
            ),
            "description": self.personal_description or "",
        }

    # ── 修改（供未来游戏循环使用）──

    def _recalc_derived(self):
        """级联更新衍生属性。规则函数从 rules 模块导入，避免循环依赖。"""
        from investigator.rules import calc_derived
        cthulhu = self.get_skill_value("克苏鲁神话")
        self.derived = calc_derived(self.stats, self.age, cthulhu)

    def modify_stat(self, stat_name: str, delta) -> tuple[int, str]:
        """Modify a core stat value. delta can be int or dice formula string like \"-1d4\".
        Returns (new_value, detail_message)."""
        from utils import roll_dice

        # Resolve delta
        if isinstance(delta, str):
            # Parse dice formula like "-1d4", "2d6+1"
            total = 0
            sign = 1
            remaining = delta.strip()
            if remaining.startswith('-'):
                sign = -1
                remaining = remaining[1:]
            elif remaining.startswith('+'):
                remaining = remaining[1:]
            # Match NdS or bare number
            dice_match = re.match(r'(\d+)[dD](\d+)', remaining)
            if dice_match:
                n = int(dice_match.group(1))
                s = int(dice_match.group(2))
                total = roll_dice(n, s)
                remaining = remaining[dice_match.end():]
                # Check for modifier like +1 or -2
                mod_match = re.match(r'([+-]\d+)', remaining)
                if mod_match:
                    total += int(mod_match.group(1))
                    remaining = remaining[mod_match.end():]
            else:
                try:
                    total = int(remaining)
                except ValueError:
                    total = 0
            delta_val = sign * total
        else:
            delta_val = int(delta)

        detail = ""
        upper = stat_name.upper()
        stats = self.stats

        # Map to Stats field
        if hasattr(stats, upper):
            old_val = getattr(stats, upper)
            new_val = max(0, old_val + delta_val)
            setattr(stats, upper, new_val)
            detail = f"{stat_name}: {old_val} -> {new_val}"

            # Recalculate derived stats if needed
            if upper in ("CON", "SIZ"):
                self.derived.HP = math.floor((stats.CON + stats.SIZ) / 10)
                detail += f", HP={self.derived.HP}"
            if upper == "POW":
                self.derived.MP = math.floor(stats.POW / 5)
                detail += f", MP={self.derived.MP}"
            if upper == "LUCK":
                # LUCK can't go above 99
                if new_val > 99:
                    setattr(stats, upper, 99)
                    detail = f"{stat_name}: {old_val} -> 99"

            return (new_val, detail)
        elif upper == "SAN":
            self.derived.SAN = max(0, self.derived.SAN + delta_val)
            detail = f"SAN: {self.derived.SAN - delta_val} -> {self.derived.SAN}"
            return (self.derived.SAN, detail)
        elif upper == "HP":
            self.derived.HP = max(0, min(self.derived.HP + delta_val, self.derived.HP_MAX))
            detail = f"HP: {self.derived.HP - delta_val} -> {self.derived.HP}"
            return (self.derived.HP, detail)
        elif upper == "MP":
            self.derived.MP = max(0, self.derived.MP + delta_val)
            detail = f"MP: {self.derived.MP - delta_val} -> {self.derived.MP}"
            return (self.derived.MP, detail)
        else:
            return (0, f"未知属性: {stat_name}")

    def modify_skill(self, name: str, delta: int):
        sk = self.get_skill(name)
        if sk:
            sk.value = max(0, min(99, sk.value + delta))

    # ── 物品便捷查询 ──

    def has_item(self, name: str) -> bool:
        """Check if investigator holds a specific item."""
        return self.item_manager.has(name)

    def list_items(self) -> str:
        """Describe all held items (formatted string)."""
        return self.item_manager.describe()

    def add_weapon(self, w: Weapon):
        self.weapons.append(w)

    def remove_weapon(self, name: str):
        self.weapons = [w for w in self.weapons if w.name != name]

    # ── 战斗已由 src/game/combat.py 的 CombatSystem 接管 ──
    # combat_check() 和 damage_roll() 的原本预留已迁移到 CombatSystem._resolve_player_action()
    # 和 _roll_damage()。此处不再提供 combat/damage 方法。

    def save(self, path: str):
        """长期存储：导出为 JSON 文件"""
        from investigator.serialization import to_json
        to_json(self, path)

    @classmethod
    def load(cls, path: str) -> "Investigator":
        """长期存储：从 JSON 文件加载"""
        from investigator.serialization import from_json
        return from_json(path)

    def __repr__(self):
        occ = self.occupation.name if self.occupation else "无职业"
        return f"Investigator({self.name}, {occ}, age={self.age})"
