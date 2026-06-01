"""武器库数据类 + 加载器."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import json
import os
import re


def _damage_str_to_dict(formula: str) -> dict:
    """Convert legacy damage formula string to structured dict."""
    f = formula.replace(" ", "")
    spec = {"dice_n": 0, "dice_d": 0, "bonus": 0, "use_db": False}
    if "/" in f:
        f = f.split("/")[0].strip()
    for part in f.split("+"):
        part = part.strip()
        if part == "DB":
            spec["use_db"] = True
        elif "D" in part:
            m = re.match(r"(\d*)D(\d+)", part)
            if m:
                spec["dice_n"] = int(m.group(1)) if m.group(1) else 1
                spec["dice_d"] = int(m.group(2))
        else:
            try:
                spec["bonus"] += int(part)
            except ValueError:
                pass
    return spec


@dataclass
class LibraryWeapon:
    name: str
    skill_name: str
    damage: dict = field(default_factory=lambda: {"dice_n": 0, "dice_d": 0, "bonus": 0, "use_db": False})
    range: str = ""
    shots: int = 0
    malfunction: int = 100
    era: str = "all"
    rarity: str = "common"
    damage_type: str = "物理"
    armor_piercing: int = 0
    attack_bonus: int = 0
    multi_attack: int = 1
    special_rules: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "skill_name": self.skill_name,
            "damage": self.damage,
            "range": self.range,
            "shots": self.shots,
            "damage_type": self.damage_type,
            "armor_piercing": self.armor_piercing,
            "attack_bonus": self.attack_bonus,
            "multi_attack": self.multi_attack,
            "malfunction": self.malfunction,
            "era": self.era,
            "rarity": self.rarity,
            "special_rules": self.special_rules,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryWeapon":
        dmg = data["damage"]
        if isinstance(dmg, str):
            dmg = _damage_str_to_dict(dmg)
        return cls(
            name=data["name"],
            skill_name=data["skill_name"],
            damage=dmg,
            range=data.get("range", ""),
            shots=data.get("shots", data.get("ammo", 0)),
            malfunction=data.get("malfunction", 100),
            era=data.get("era", "all"),
            rarity=data.get("rarity", "common"),
            damage_type=data.get("damage_type", "物理"),
            armor_piercing=data.get("armor_piercing", 0),
            attack_bonus=data.get("attack_bonus", 0),
            multi_attack=data.get("multi_attack", data.get("attacks_per_round", 1)),
            special_rules=data.get("special_rules", ""),
            description=data.get("description", ""),
        )


class WeaponLibrary:
    """武器库管理器 —— 加载 core + extensions，提供查询."""

    def __init__(self):
        self._weapons: dict[str, LibraryWeapon] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "library", "core", "weapons.json"
            )
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            weapon = LibraryWeapon.from_dict(item)
            self._weapons[weapon.name] = weapon

    def get(self, name: str) -> Optional[LibraryWeapon]:
        return self._weapons.get(name)

    def list_all(self) -> list[LibraryWeapon]:
        return list(self._weapons.values())

    def search(self, era: str = None, rarity: str = None, keyword: str = None) -> list[LibraryWeapon]:
        results = []
        for w in self._weapons.values():
            if era and w.era != "all" and w.era != era:
                continue
            if rarity and w.rarity != rarity:
                continue
            if keyword and keyword.lower() not in w.name.lower():
                continue
            results.append(w)
        return results

    def __len__(self) -> int:
        return len(self._weapons)

    def __repr__(self) -> str:
        return f"WeaponLibrary({len(self._weapons)} weapons)"
