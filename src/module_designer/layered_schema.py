"""三层 JSON Schema 定义 + 验证."""
from __future__ import annotations
from typing import List, Optional


# ═══════════════════════════════════════════════════════════════
#  L1 玩家可见层 Schema
# ═══════════════════════════════════════════════════════════════

L1_PERCEPTIBLE_TYPES = {"object", "sound", "smell", "sight", "touch", "intuition"}

L1_PERCEPTIBLE_SCHEMA = {
    "type": {"required": False, "values": L1_PERCEPTIBLE_TYPES},
    "name": {"required": True},
    "brief": {"required": True},
    "linked_interaction": {"required": False},
}

L1_NPC_APPEARANCE_SCHEMA = {
    "name": {"required": True},
    "brief": {"required": True},
    "demeanor": {"required": False},
}

L1_SCENE_SCHEMA = {
    "description": {"required": False},
    "atmosphere": {"required": False},
    "perceptible": {"required": False, "list_of": L1_PERCEPTIBLE_SCHEMA},
    "ambient_hints": {"required": False},
    "npc_appearances": {"required": False, "list_of": L1_NPC_APPEARANCE_SCHEMA},
}


# ═══════════════════════════════════════════════════════════════
#  L2 KP 守秘人层 Schema
# ═══════════════════════════════════════════════════════════════

L2_DIFFICULTIES = {"None", "regular", "hard", "extreme"}

L2_INTERACTION_SCHEMA = {
    "type": {"required": True},
    "name": {"required": True},
    "requirement": {"required": False},
    "trigger": {"required": False},
    "result": {"required": False},
    "side_effects": {"required": False},
    "difficulty": {"required": False, "values": L2_DIFFICULTIES},
    "based_on": {"required": False},
    "graded_result": {"required": False},
}

L2_AUTO_TRIGGER_SCHEMA = L2_INTERACTION_SCHEMA  # 统一字段模型

L2_EVENT_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "type": {"required": False},
    "requirement": {"required": False},
    "trigger": {"required": False},
    "result": {"required": False},
    "side_effects": {"required": False},
    "difficulty": {"required": False},
    "based_on": {"required": False},
    "graded_result": {"required": False},
    "extra": {"required": False},
}

L2_NPC_PROFILE_SCHEMA = {
    "name": {"required": True},
    "role": {"required": False},
    "personality_notes": {"required": False},
    "appearance": {"required": False},
    "what_they_can_do": {"required": False},
    "interaction_triggers": {"required": False},
    "initial_state": {"required": False},
    "initial_attitude": {"required": False},
    "initial_following": {"required": False},
    "can_interact": {"required": False},
    "can_follow": {"required": False},
    "follow_requirements": {"required": False},
    "interact_requirements": {"required": False},
}

L2_BOSS_ENCOUNTER_SCHEMA = {
    "id": {"required": True},
    "type": {"required": False},
    "engage_type": {"required": False, "values": ["at", "interaction", "event"]},
    "boss_ref": {"required": True},
    "scene": {"required": False},
    "requirements": {"required": False},
    "description": {"required": False},
}

L2_SCENE_SCHEMA = {
    "description": {"required": False},
    "from_here": {"required": False},
    "to_here": {"required": False},
    "interactions": {"required": False, "list_of": L2_INTERACTION_SCHEMA},
    "auto_triggers": {"required": False, "list_of": L2_AUTO_TRIGGER_SCHEMA},
    "encounters": {"required": False},
    "scene_weapons": {"required": False},
    "extra": {"required": False},
}


# ═══════════════════════════════════════════════════════════════
#  L3 设计者层 Schema
# ═══════════════════════════════════════════════════════════════

L3_MODULE_META_SCHEMA = {
    "title": {"required": False},
    "author": {"required": False},
    "era": {"required": False},
    "theme": {"required": False},
    "expected_duration": {"required": False},
    "player_count": {"required": False},
}

L3_WORLD_RULE_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "rule": {"required": True},
    "scope": {"required": False},
    "is_absolute": {"required": False},
}

L3_SCENE_INTENT_SCHEMA = {
    "purpose": {"required": False},
    "key_threat": {"required": False},
    "notes": {"required": False},
}

L3_ENDING_CONDITION_SCHEMA = {
    "id": {"required": True},
    "condition": {"required": False},
    "narrative": {"required": False},
}

L3_TONE_CONSTRAINTS_SCHEMA = {
    "genre": {"required": False},
    "forbidden": {"required": False},
    "recommended": {"required": False},
    "narrative_style": {"required": False},
}

L3_CHARACTER_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "behavior": {"required": False},
}

L3_TOP_SCHEMA = {
    "module_meta": {"required": False, "nested": L3_MODULE_META_SCHEMA},
    "world_rules": {"required": False, "list_of": L3_WORLD_RULE_SCHEMA},
    "scene_intents": {"required": False},
    "ending_conditions": {"required": False, "list_of": L3_ENDING_CONDITION_SCHEMA},
    "tone_constraints": {"required": False, "nested": L3_TONE_CONSTRAINTS_SCHEMA},
    "characters": {"required": False, "list_of": L3_CHARACTER_SCHEMA},
    "driving_force": {"required": False},
    "narrative_lines": {"required": False, "list_of": {
        "name": {"required": False},
        "outline": {"required": False},
        "key_scenes": {"required": False},
        "type": {"required": False},
    }},
    "time_pressure": {
        "required": False,
        "nested": {
            "name": {"required": False},
            "guide": {"required": False},
            "urgency": {"required": False},
            "urgency_max": {"required": False},
            "key_signals": {"required": False},
        },
    },
}


# ═══════════════════════════════════════════════════════════════
#  验证引擎
# ═══════════════════════════════════════════════════════════════

class SchemaViolation:
    """单条验证违规."""
    def __init__(self, path: str, message: str, severity: str = "error"):
        self.path = path
        self.message = message
        self.severity = severity  # error / warning / info

    def __repr__(self):
        return f"[{self.severity}] {self.path}: {self.message}"


class SchemaReport:
    """验证报告."""
    def __init__(self):
        self.violations: List[SchemaViolation] = []

    def add(self, path: str, message: str, severity: str = "error"):
        self.violations.append(SchemaViolation(path, message, severity))

    @property
    def errors(self) -> List[SchemaViolation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> List[SchemaViolation]:
        return [v for v in self.violations if v.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        if not self.violations:
            return "验证通过，无问题。"
        lines = [f"验证完成：{len(self.errors)} 错误, {len(self.warnings)} 警告"]
        for v in self.violations:
            lines.append(f"  {v}")
        return "\n".join(lines)

    def __bool__(self):
        return self.is_valid


def _validate_value(data: dict, field: str, rules: dict, path: str, report: SchemaReport):
    """验证单个字段的值是否符合 schema 规则."""
    value = data.get(field)

    # 必填检查
    if rules.get("required") and (value is None or (isinstance(value, str) and value == "")):
        report.add(f"{path}.{field}", f"必填字段缺失", "warning")
        return

    if value is None:
        return

    # 枚举值检查
    if "values" in rules and isinstance(value, str):
        if value not in rules["values"]:
            report.add(
                f"{path}.{field}",
                f"'{value}' 不是有效值，允许：{rules['values']}",
                "warning",
            )

    # 嵌套对象检查
    if "nested" in rules and isinstance(value, dict):
        _validate_object(value, rules["nested"], f"{path}.{field}", report)

    # 列表元素检查
    if "list_of" in rules and isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict):
                _validate_object(item, rules["list_of"], f"{path}.{field}[{i}]", report)


def _validate_object(data: dict, schema: dict, path: str, report: SchemaReport):
    """验证一个 dict 是否符合 object schema."""
    if not isinstance(data, dict):
        report.add(path, f"应为对象，实际类型：{type(data).__name__}", "error")
        return
    for field, rules in schema.items():
        _validate_value(data, field, rules, path, report)


def validate_l1(data: dict) -> SchemaReport:
    """验证 L1 JSON 数据（顶层为 {scene_name: SceneL1, ...}）."""
    report = SchemaReport()
    if not isinstance(data, dict):
        report.add("L1", "L1 数据应为 dict（scene_name → SceneL1）", "error")
        return report
    for scene_name, scene_data in data.items():
        if not isinstance(scene_data, dict):
            report.add(f"L1.{scene_name}", "场景数据应为 dict", "error")
            continue
        _validate_object(scene_data, L1_SCENE_SCHEMA, f"L1.{scene_name}", report)
    return report


def validate_l2(data: dict) -> SchemaReport:
    """验证 L2 JSON 数据（顶层 scenes + events + npc_profiles）."""
    report = SchemaReport()
    if not isinstance(data, dict):
        report.add("L2", "L2 数据应为 dict", "error")
        return report

    # 验证 scenes
    scenes = data.get("scenes", {})
    if not isinstance(scenes, dict):
        report.add("L2.scenes", "scenes 应为 dict", "error")
    else:
        for scene_name, scene_data in scenes.items():
            if not isinstance(scene_data, dict):
                report.add(f"L2.scenes.{scene_name}", "场景数据应为 dict", "error")
                continue
            _validate_object(scene_data, L2_SCENE_SCHEMA, f"L2.scenes.{scene_name}", report)

    # 验证 events
    events = data.get("events", [])
    if not isinstance(events, list):
        report.add("L2.events", "events 应为 list", "error")
    else:
        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                report.add(f"L2.events[{i}]", "事件数据应为 dict", "error")
                continue
            _validate_object(ev, L2_EVENT_SCHEMA, f"L2.events[{i}]", report)

    # 验证 npc_profiles
    npc_profiles = data.get("npc_profiles", {})
    if isinstance(npc_profiles, dict):
        for npc_name, npc_data in npc_profiles.items():
            if not isinstance(npc_data, dict):
                report.add(f"L2.npc_profiles.{npc_name}", "NPC 数据应为 dict", "error")
                continue
            _validate_object(npc_data, L2_NPC_PROFILE_SCHEMA, f"L2.npc_profiles.{npc_name}", report)

    # 验证 boss_encounters
    boss_encounters = data.get("boss_encounters", [])
    if isinstance(boss_encounters, list):
        for i, be in enumerate(boss_encounters):
            _validate_object(be, L2_BOSS_ENCOUNTER_SCHEMA, f"L2.boss_encounters[{i}]", report)

    return report


def validate_l3(data: dict) -> SchemaReport:
    """验证 L3 JSON 数据."""
    report = SchemaReport()
    if not isinstance(data, dict):
        report.add("L3", "L3 数据应为 dict", "error")
        return report

    _validate_object(data, L3_TOP_SCHEMA, "L3", report)

    # 验证 scene_intents（value 是 dict of SceneIntent）
    scene_intents = data.get("scene_intents", {})
    if isinstance(scene_intents, dict):
        for scene_name, intent_data in scene_intents.items():
            if not isinstance(intent_data, dict):
                report.add(f"L3.scene_intents.{scene_name}", "应为 dict", "error")
                continue
            _validate_object(intent_data, L3_SCENE_INTENT_SCHEMA, f"L3.scene_intents.{scene_name}", report)

    return report


def validate_all(l1_data: dict, l2_data: dict, l3_data: dict) -> dict[str, SchemaReport]:
    """验证全部三层数据."""
    return {
        "L1": validate_l1(l1_data),
        "L2": validate_l2(l2_data),
        "L3": validate_l3(l3_data),
    }


def is_valid(l1_data: dict, l2_data: dict, l3_data: dict) -> bool:
    """三层数据是否全部通过验证."""
    reports = validate_all(l1_data, l2_data, l3_data)
    return all(r.is_valid for r in reports.values())
