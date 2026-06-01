"""Boss library — loads boss templates from JSON."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class LibraryBoss:
    """Boss template data from bosses.json."""
    name: str
    type: str = ""
    attributes: dict = field(default_factory=dict)
    armor: str = ""
    attacks: list = field(default_factory=list)
    special_abilities: list = field(default_factory=list)
    san_loss: str = ""
    description: str = ""
    boss_mechanics: str = ""
    flags: list[str] = field(default_factory=list)
    multi_attack: int = 1
    damage_multipliers: dict = field(default_factory=dict)
    dodge_bonus: int = 0
    phases: list = field(default_factory=list)
    special_rules: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryBoss":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", ""),
            attributes=data.get("attributes", {}),
            armor=data.get("armor", ""),
            attacks=data.get("attacks", []),
            special_abilities=data.get("special_abilities", []),
            san_loss=data.get("san_loss", ""),
            description=data.get("description", ""),
            boss_mechanics=data.get("boss_mechanics", ""),
            flags=data.get("flags", []),
            multi_attack=data.get("multi_attack", 1),
            damage_multipliers=data.get("damage_multipliers", {}),
            dodge_bonus=data.get("dodge_bonus", 0),
            phases=data.get("phases", []),
            special_rules=data.get("special_rules", ""),
        )


class BossLibrary:
    """Loads and queries boss templates from bosses.json."""

    def __init__(self, core_path: str, extensions_dir: str | None = None):
        self._bosses: dict[str, LibraryBoss] = {}
        self._load(core_path)
        if extensions_dir:
            self._load_extensions(extensions_dir)

    def _load(self, path: str):
        p = Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        for name, bdata in data.items():
            bdata.setdefault("name", name)
            self._bosses[name] = LibraryBoss.from_dict(bdata)

    def _load_extensions(self, extensions_dir: str):
        ext = Path(extensions_dir)
        if ext.is_dir():
            for f in ext.glob("*.json"):
                self._load(str(f))

    def get(self, boss_ref: str) -> LibraryBoss | None:
        return self._bosses.get(boss_ref)

    def list_names(self) -> list[str]:
        return list(self._bosses.keys())

    def __len__(self) -> int:
        return len(self._bosses)
