"""L1 玩家可见层数据模型."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Perceptible:
    """玩家无需检定即可感知的元素."""
    type: str            # object / sound / smell / sight / touch / intuition
    name: str
    brief: str           # 一句话描述
    linked_interaction: Optional[str] = None   # 关联 L2 interaction.name

    def to_dict(self) -> dict:
        d = {"type": self.type, "name": self.name, "brief": self.brief}
        if self.linked_interaction:
            d["linked_interaction"] = self.linked_interaction
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Perceptible":
        return cls(
            type=data["type"],
            name=data["name"],
            brief=data["brief"],
            linked_interaction=data.get("linked_interaction"),
        )


@dataclass
class NPCAppearance:
    """NPC 外貌描述（玩家可见部分）."""
    name: str
    brief: str
    demeanor: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "brief": self.brief, "demeanor": self.demeanor}

    @classmethod
    def from_dict(cls, data: dict) -> "NPCAppearance":
        return cls(
            name=data["name"],
            brief=data["brief"],
            demeanor=data.get("demeanor", ""),
        )


@dataclass
class SceneL1:
    """单个场景的 L1 信息."""
    scene_name: str
    description: str = ""
    atmosphere: str = ""
    mood: str = "uneasy"        # confused / uneasy / tense / terrified / hopeful / desperate
    perceptible: List[Perceptible] = field(default_factory=list)
    ambient_hints: List[str] = field(default_factory=list)
    npc_appearances: List[NPCAppearance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "atmosphere": self.atmosphere,
            "mood": self.mood,
            "perceptible": [p.to_dict() for p in self.perceptible],
            "ambient_hints": self.ambient_hints,
            "npc_appearances": [n.to_dict() for n in self.npc_appearances],
        }

    @classmethod
    def from_dict(cls, data: dict, scene_name: str = "") -> "SceneL1":
        return cls(
            scene_name=scene_name,
            description=data.get("description", ""),
            atmosphere=data.get("atmosphere", ""),
            mood=data.get("mood", "uneasy"),
            perceptible=[Perceptible.from_dict(p) for p in data.get("perceptible", [])],
            ambient_hints=data.get("ambient_hints", []),
            npc_appearances=[NPCAppearance.from_dict(n) for n in data.get("npc_appearances", [])],
        )


def load_l1(path: str) -> dict[str, SceneL1]:
    """从 JSON 加载 L1 数据."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {name: SceneL1.from_dict(sd, name) for name, sd in data.items()}


def save_l1(l1_data: dict[str, SceneL1], path: str) -> None:
    """保存 L1 数据到 JSON."""
    import json, os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = {name: scene.to_dict() for name, scene in l1_data.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
