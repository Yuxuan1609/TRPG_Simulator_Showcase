"""L2 KP 守秘人层数据模型 —— 现有 Interaction/GameEvent 对齐 + 扩展."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

# NPCProfile has been migrated to src/game/npc_manager.NPC
# This alias maintains backward compatibility for pipeline consumers
from game.npc_manager import NPC as NPCProfile


@dataclass
class Encounter:
    """场景中的敌人遭遇声明."""
    enemy_ref: str
    trigger_condition: str = ""
    initial_behavior: str = ""
    quantity: int = 1
    notes: Optional[str] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "enemy_ref": self.enemy_ref,
            "trigger_condition": self.trigger_condition,
            "initial_behavior": self.initial_behavior,
            "quantity": self.quantity,
        }
        if self.notes:
            d["notes"] = self.notes
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Encounter":
        return cls(
            enemy_ref=data["enemy_ref"],
            trigger_condition=data.get("trigger_condition", ""),
            initial_behavior=data.get("initial_behavior", ""),
            quantity=data.get("quantity", 1),
            notes=data.get("notes"),
            extra=data.get("extra"),
        )


@dataclass
class SceneWeapon:
    """场景中可获取的武器."""
    weapon_ref: str
    location: str = ""
    discovery_method: str = ""
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {"weapon_ref": self.weapon_ref, "location": self.location, "discovery_method": self.discovery_method}
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SceneWeapon":
        return cls(
            weapon_ref=data["weapon_ref"],
            location=data.get("location", ""),
            discovery_method=data.get("discovery_method", ""),
            extra=data.get("extra"),
        )


@dataclass
class AutoTrigger:
    """自动触发事件（与 interaction 统一字段模型）."""
    id: str                      # AT1, AT2...
    name: str
    scene: str = ""              # 生效场景 ID (S1, S2...)
    type: str = ""               # 关联技能名，不涉及填"无"
    requirement: str = ""        # 前置条件（自然语言）
    trigger: str = ""            # 触发条件描述
    result: str = ""             # 触发后结果描述
    side_effects: list = field(default_factory=list)  # 自然语言字符串列表
    difficulty: str = ""         # None / regular / hard / extreme
    based_on: str = ""           # 派生来源 interaction ID
    graded_result: Optional[dict] = None  # 分级检定后果
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "name": self.name, "scene": self.scene,
            "type": self.type,
            "requirement": self.requirement,
            "trigger": self.trigger,
            "result": self.result,
            "side_effects": self.side_effects,
            "difficulty": self.difficulty,
            "based_on": self.based_on,
        }
        if self.graded_result:
            d["graded_result"] = self.graded_result
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AutoTrigger":
        return cls(
            id=data["id"], name=data["name"],
            scene=data.get("scene", ""),
            type=data.get("type", ""),
            requirement=data.get("requirement", ""),
            trigger=data.get("trigger", ""),
            result=data.get("result", ""),
            side_effects=data.get("side_effects", []),
            difficulty=data.get("difficulty", ""),
            based_on=data.get("based_on", ""),
            graded_result=data.get("graded_result"),
            extra=data.get("extra"),
        )


@dataclass
class SceneL2:
    """单个场景的 L2 KP 信息."""
    scene_name: str
    description: str = ""
    from_here: list = field(default_factory=list)
    to_here: list = field(default_factory=list)
    interactions: list = field(default_factory=list)   # list[Interaction]
    encounters: List[Encounter] = field(default_factory=list)
    scene_weapons: List[SceneWeapon] = field(default_factory=list)
    auto_triggers: List[AutoTrigger] = field(default_factory=list)
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "description": self.description,
            "from_here": self.from_here,
            "to_here": self.to_here,
            "interactions": self.interactions,
            "encounters": [e.to_dict() for e in self.encounters],
            "scene_weapons": [sw.to_dict() for sw in self.scene_weapons],
            "auto_triggers": [at.to_dict() for at in self.auto_triggers],
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict, scene_name: str = "") -> "SceneL2":
        return cls(
            scene_name=scene_name,
            description=data.get("description", ""),
            from_here=data.get("from_here", []),
            to_here=data.get("to_here", []),
            interactions=data.get("interactions", []),
            encounters=[Encounter.from_dict(e) for e in data.get("encounters", [])],
            scene_weapons=[SceneWeapon.from_dict(sw) for sw in data.get("scene_weapons", [])],
            auto_triggers=[AutoTrigger.from_dict(at) for at in data.get("auto_triggers", [])],
            extra=data.get("extra"),
        )


def _normalize_npc_profile(data: dict) -> dict:
    """Map old NPC fields to new NPC dataclass fields."""
    return {
        "name": data.get("name", ""),
        "role": data.get("role", ""),
        "personality_notes": data.get("personality_notes") or data.get("personality", ""),
        "appearance": data.get("appearance", ""),
        "what_they_can_do": data.get("what_they_can_do", ""),
        "interaction_triggers": data.get("interaction_triggers", []),
        "can_follow": data.get("can_follow", False),
        "follow_requirements": data.get("follow_requirements", ""),
        "can_interact": data.get("can_interact", True),
        "interact_requirements": data.get("interact_requirements", ""),
        "initial_state": data.get("initial_state", "alive"),
        "initial_attitude": data.get("initial_attitude", "neutral"),
        "initial_following": data.get("initial_following", False),
        "bound_interactions": data.get("bound_interactions", []),
        "bound_auto_triggers": data.get("bound_auto_triggers", []),
        "scene": data.get("scene", ""),
    }


def load_l2(path: str) -> dict:
    """从 JSON 加载 L2 数据."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    scenes = {name: SceneL2.from_dict(sd, name) for name, sd in data.get("scenes", {}).items()}
    events = data.get("events", [])
    npc_profiles = {
        name: _normalize_npc_profile(np)
        for name, np in data.get("npc_profiles", {}).items()
    }
    return {"scenes": scenes, "events": events, "npc_profiles": npc_profiles}


def save_l2(l2_data: dict, path: str) -> None:
    """保存 L2 数据到 JSON."""
    import json, os
    os.makedirs(os.path.dirname(path), exist_ok=True)

    npc_data = l2_data.get("npc_profiles", {})
    out_npc = {}
    for name, np in npc_data.items():
        if isinstance(np, dict):
            out_npc[name] = _normalize_npc_profile(np)
        elif hasattr(np, "to_dict"):
            out_npc[name] = np.to_dict()
        else:
            from dataclasses import asdict as _asdict
            out_npc[name] = _asdict(np)

    out = {
        "scenes": {name: scene.to_dict() for name, scene in l2_data["scenes"].items()},
        "events": l2_data.get("events", []),
        "npc_profiles": out_npc,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
