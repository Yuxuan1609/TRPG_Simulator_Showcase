"""Side effect dataclasses and @markup parsing. Pure data + parser, no LLM/app logic."""
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class ItemGain:
    item_name: str
    quantity: int = 1


@dataclass
class ConsumeItem:
    item_name: str
    quantity: int = 1
    narrative: str = ""


@dataclass
class StatChange:
    stat_name: str
    delta: int | str = 0
    narrative: str = ""


@dataclass
class SpawnEnemy:
    enemy_ref: str
    scene: str
    quantity: int = 1


@dataclass
class GrantWeapon:
    weapon_ref: str
    scene: str = ""
    quantity: int = 1


@dataclass
class SceneWeapon:
    weapon_ref: str
    scene: str
    quantity: int = 1


@dataclass
class NPCStateChange:
    npc_name: str
    new_state: str


@dataclass
class NPCFollow:
    npc_name: str
    follow: bool = True


# ── @markup parsing ──

_MARKUP_PATTERN = re.compile(
    r'@(spawn_enemy|grant_weapon|stat_change|item_gain|consume_item|npc_state_change|npc_follow)'
    r'\(([^)]*)\)'
)


def _parse_kwargs(kwargs_str: str) -> dict:
    """Parse key=value pairs from @markup arg string. Values may be quoted."""
    result = {}
    if not kwargs_str.strip():
        return result
    for match in re.findall(r'(\w+)\s*=\s*(?:"""([^"]*)"""|"([^"]*)"|\'([^\']*)\'|([^,)]+))', kwargs_str):
        key = match[0]
        value = match[1] or match[2] or match[3] or match[4]
        value = value.strip().rstrip(',')
        result[key] = value
    return result


def _build_side_effect(func_name: str, kwargs: dict):
    """Build a side effect dataclass from function name and parsed kwargs."""
    if func_name == "spawn_enemy":
        return SpawnEnemy(
            enemy_ref=kwargs.get("enemy_ref", ""),
            scene=kwargs.get("scene", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "grant_weapon":
        return GrantWeapon(
            weapon_ref=kwargs.get("weapon_ref", ""),
            scene=kwargs.get("scene", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "stat_change":
        delta_str = kwargs.get("delta", "0")
        try:
            delta = int(delta_str)
        except ValueError:
            delta = delta_str
        return StatChange(
            stat_name=kwargs.get("stat_name", ""),
            delta=delta,
            narrative=kwargs.get("narrative", ""),
        )
    elif func_name == "item_gain":
        return ItemGain(
            item_name=kwargs.get("item_name", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "consume_item":
        return ConsumeItem(
            item_name=kwargs.get("item_name", ""),
            quantity=int(kwargs.get("quantity", 1)),
            narrative=kwargs.get("narrative", ""),
        )
    elif func_name == "npc_state_change":
        return NPCStateChange(
            npc_name=kwargs.get("npc_name", ""),
            new_state=kwargs.get("new_state", ""),
        )
    elif func_name == "npc_follow":
        follow_str = kwargs.get("follow", "true").lower()
        return NPCFollow(
            npc_name=kwargs.get("npc_name", ""),
            follow=follow_str in ("true", "1", "yes"),
        )
    return None


def parse_markup(text: str):
    """Parse a single @function(args) markup string into a side effect dataclass."""
    match = _MARKUP_PATTERN.search(text)
    if not match:
        return None
    func_name = match.group(1)
    kwargs_str = match.group(2)
    return _build_side_effect(func_name, _parse_kwargs(kwargs_str))


def parse_markup_all(text: str) -> list:
    """Parse all @markup occurrences in a string."""
    results = []
    for match in _MARKUP_PATTERN.finditer(text):
        func_name = match.group(1)
        kwargs_str = match.group(2)
        effect = _build_side_effect(func_name, _parse_kwargs(kwargs_str))
        if effect is not None:
            results.append(effect)
    return results
