"""双层判定系统：T1 确定性引擎 + T2 LLM 增强."""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING
import random

from config import JUDGMENT_TIER2_ENABLED

if TYPE_CHECKING:
    from library.enemies import LibraryEnemy, SpecialAbility
    from library.weapons import LibraryWeapon
    from scenario_core import ScenarioWorld


class Tier1Result:
    """确定性引擎的判定结果."""

    def __init__(self, success: bool, roll: int, target: int, detail: str = ""):
        self.success = success
        self.roll = roll
        self.target = target
        self.detail = detail

    def __repr__(self):
        status = "成功" if self.success else "失败"
        return f"Tier1Result({status}, roll={self.roll}, target={self.target})"


class JudgmentEngine:
    """
    双层判定引擎。
    - tier1_enabled: 始终 True（确定性检定必须有）
    - tier2_enabled: 可开关，决定是否调用 LLM 增强
    """

    def __init__(self, tier2_enabled: bool = JUDGMENT_TIER2_ENABLED):
        self.tier2_enabled = tier2_enabled

    # ── Tier 1: 确定性 ──

    def tier1_skill_check(self, skill_value: int, difficulty: str = "regular") -> Tier1Result:
        """
        COC 7th D100 技能检定。
        difficulty: regular(技能值), hard(技能值/2), extreme(技能值/5)
        """
        roll = random.randint(1, 100)
        if difficulty == "hard":
            target = skill_value // 2
        elif difficulty == "extreme":
            target = skill_value // 5
        else:
            target = skill_value
        success = roll <= target
        detail = f"D100={roll}/{target} {'成功' if success else '失败'}"
        return Tier1Result(success, roll, target, detail)

    def tier1_damage_roll(self, damage_formula: str, db: int = 0) -> tuple[int, str]:
        """
        解析伤害公式并掷骰。
        支持: "1D8+DB", "2D6+4", "1D3", "4D6/2D6/1D6"
        """
        formula = damage_formula.replace("DB", str(db))
        if "/" in formula:
            formula = formula.split("/")[0]
        parts = formula.replace("+", " ").replace("-", " -").split()
        total = 0
        detail_parts = []
        for part in parts:
            if part.startswith("-"):
                sign = -1
                part = part[1:]
            else:
                sign = 1
            if "D" in part.upper():
                count_str, sides_str = part.upper().split("D")
                count = int(count_str) if count_str else 1
                sides = int(sides_str)
                roll = sum(random.randint(1, sides) for _ in range(count))
                total += sign * roll
                detail_parts.append(f"{part}({roll})")
            else:
                total += sign * int(part)
                detail_parts.append(part)
        detail = " + ".join(detail_parts) + f" = {total}"
        return total, detail

    def tier1_san_check(self, san_loss: str) -> tuple[int, int, str]:
        """解析 SAN 损失公式 "成功损失/失败损失" → (成功损失, 失败损失)"""
        parts = san_loss.split("/")
        success_loss = self._parse_san_part(parts[0]) if len(parts) > 0 else 0
        fail_loss = self._parse_san_part(parts[1]) if len(parts) > 1 else success_loss
        return success_loss, fail_loss, san_loss

    def _parse_san_part(self, s: str) -> int:
        s = s.strip()
        if s == "0":
            return 0
        if "D" in s.upper():
            count_str, sides_str = s.upper().replace("D", " ").split()
            count = int(count_str) if count_str else 1
            sides = int(sides_str)
            return sum(random.randint(1, sides) for _ in range(count))
        return int(s) if s.isdigit() else 0

    # ── Tier 2: LLM 增强（桩，prompt 构建由 prompts.py 负责）──

    def build_tier2_context(
        self,
        tier1: Tier1Result,
        enemy: "LibraryEnemy" = None,
        weapon: "LibraryWeapon" = None,
        world: "ScenarioWorld" = None,
    ) -> str:
        """构建供 LLM 做 Tier 2 判定的上下文."""
        parts = [f"T1 检定结果: 掷骰={tier1.roll}, 目标={tier1.target}, {'成功' if tier1.success else '失败'}"]
        if enemy:
            parts.append(f"敌人: {enemy.name}")
            parts.append(f"特殊能力: {', '.join(a.name for a in enemy.special_abilities)}")
            parts.append(f"战斗行为: {enemy.combat_behavior}")
        if weapon:
            parts.append(f"武器: {weapon.name} ({weapon.damage})")
            if weapon.special_rules:
                parts.append(f"武器规则: {weapon.special_rules}")
        return "\n".join(parts)
