"""EnemyInstance + EnemyManager — runtime enemy tracking."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid

from library.enemies import EnemyLibrary


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class EnemyInstance:
    instance_id: str
    enemy_ref: str
    scene: str
    quantity: int = 1
    status: str = "neutral"
    flags: list[str] = field(default_factory=list)
    combat_behavior: str = ""
    description: str = ""
    # ── 战斗属性桥接（从 LibraryEnemy 拷贝）──
    attributes: dict = field(default_factory=dict)
    armor: str = ""
    attacks: list = field(default_factory=list)
    special_abilities: list = field(default_factory=list)
    san_loss: str = ""
    hp: int = 0
    boss_mechanics: str = ""
    multi_attack: int = 1
    damage_multipliers: dict = field(default_factory=dict)
    dodge_bonus: int = 0
    special_rules: str = ""
    phases: list = field(default_factory=list)
    _current_phase: str = ""


class EnemyManager:
    def __init__(self, enemy_library: EnemyLibrary):
        self._library = enemy_library
        self._instances: dict[str, EnemyInstance] = {}
        self._combat_active: bool = False
        self._combat_enemies: list[str] = []

    def spawn(self, enemy_ref: str, scene: str, quantity: int = 1) -> EnemyInstance:
        lib_enemy = self._library.get(enemy_ref)
        if not lib_enemy:
            raise KeyError(f"Enemy '{enemy_ref}' not found in library")

        # 同场景同类型合并：scene + enemy_ref 作为群组 key
        for existing in self._instances.values():
            if existing.scene == scene and existing.enemy_ref == enemy_ref:
                existing.quantity += quantity
                attrs = existing.attributes
                base_hp = (attrs.get("CON", 50) + attrs.get("SIZ", 50)) // 10 * existing.quantity
                existing.hp = base_hp
                return existing

        instance_id = f"{enemy_ref}_{_short_id()}"
        attrs = lib_enemy.attributes
        base_hp = (attrs.get("CON", 50) + attrs.get("SIZ", 50)) // 10 * quantity
        inst = EnemyInstance(
            instance_id=instance_id,
            enemy_ref=enemy_ref,
            scene=scene,
            quantity=quantity,
            status=getattr(lib_enemy, 'status', 'hostile'),
            combat_behavior=lib_enemy.combat_behavior,
            description=lib_enemy.description,
            attributes=dict(attrs),
            armor=lib_enemy.armor,
            attacks=list(lib_enemy.attacks),
            special_abilities=list(lib_enemy.special_abilities),
            san_loss=lib_enemy.san_loss,
            hp=base_hp,
        )
        inst.multi_attack = getattr(lib_enemy, 'multi_attack', 1)
        inst.damage_multipliers = dict(getattr(lib_enemy, 'damage_multipliers', {}))
        inst.dodge_bonus = getattr(lib_enemy, 'dodge_bonus', 0)
        inst.special_rules = getattr(lib_enemy, 'special_rules', '')
        inst.phases = list(getattr(lib_enemy, 'phases', []))
        inst.boss_mechanics = getattr(lib_enemy, 'boss_mechanics', '')
        self._instances[instance_id] = inst
        return inst

    def remove(self, instance_id: str):
        self._instances.pop(instance_id, None)
        if instance_id in self._combat_enemies:
            self._combat_enemies.remove(instance_id)

    def get_active_in_scene(self, scene: str) -> list[EnemyInstance]:
        return [
            i for i in self._instances.values()
            if i.scene == scene and i.status not in ("dead", "defeated")
        ]

    def get_active_in_range(self, scene: str, graph) -> list[EnemyInstance]:
        candidates = self.get_active_in_scene(scene)
        for inst in self._instances.values():
            if "adjacent_aware" not in inst.flags:
                continue
            if inst.status in ("dead", "defeated"):
                continue
            if inst in candidates:
                continue  # already in queried scene via get_active_in_scene
            # Check if queried scene is adjacent to the enemy's scene
            node = graph.nodes.get(inst.scene)
            if node:
                for edge in node.edges:
                    if edge.target == scene:
                        candidates.append(inst)
                        break
        return candidates

    def get_active_in_scene_snapshot(self, scene: str) -> list[dict]:
        """Lightweight dict list for world snapshot."""
        return [
            {
                "enemy_ref": i.enemy_ref,
                "status": i.status,
                "flags": i.flags,
                "quantity": i.quantity,
            }
            for i in self._instances.values()
            if i.scene == scene and i.status not in ("dead", "defeated")
        ]

    def group_by_ref(self, scene: str) -> dict[str, list[EnemyInstance]]:
        groups: dict[str, list[EnemyInstance]] = {}
        for inst in self.get_active_in_scene(scene):
            groups.setdefault(inst.enemy_ref, []).append(inst)
        return groups

    def set_status(self, instance_id: str, status: str):
        if instance_id in self._instances:
            self._instances[instance_id].status = status

    def register(self, instance: EnemyInstance):
        """Register an externally-created EnemyInstance (e.g. boss)."""
        self._instances[instance.instance_id] = instance

    def add_to_combat(self, instance_id: str):
        if instance_id in self._instances and instance_id not in self._combat_enemies:
            self._instances[instance_id].status = "engaged"
            self._combat_enemies.append(instance_id)
        if not self._combat_active:
            self._combat_active = True

    def mark_defeated(self, instance_id: str):
        self.set_status(instance_id, "defeated")

    def mark_dead(self, instance_id: str):
        self.set_status(instance_id, "defeated")

    def get_by_id(self, instance_id: str) -> Optional[EnemyInstance]:
        return self._instances.get(instance_id)

    def enter_combat(self, instance_ids: list[str]):
        for iid in instance_ids:
            if iid in self._instances:
                self._instances[iid].status = "engaged"
        self._combat_enemies = list(instance_ids)
        self._combat_active = True

    def exit_combat(self, result: dict):
        outcome = result.get("outcome", "")
        if outcome == "win":
            for iid in self._combat_enemies:
                inst = self._instances.get(iid)
                if inst:
                    inst.status = "defeated"
        else:
            for iid in self._combat_enemies:
                inst = self._instances.get(iid)
                if inst and inst.status == "engaged":
                    inst.status = "hostile"
        self._combat_enemies.clear()
        self._combat_active = False

    def get_combat_context(self, scene: str, graph=None) -> Optional[str]:
        candidates = self.get_active_in_range(scene, graph) if graph \
                     else self.get_active_in_scene(scene)
        if not candidates:
            return None
        lines = []
        for inst in candidates:
            flags_str = " ".join(f"[{f}]" for f in inst.flags) if inst.flags else ""
            lines.append(
                f"- [{inst.enemy_ref}] x{inst.quantity} | {inst.status}"
                + (f" | {flags_str}" if flags_str else "")
                + f"\n  习性：{inst.combat_behavior}"
                + (f"\n  描述：{inst.description}" if inst.description else "")
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        instances_dict = {}
        for iid, inst in self._instances.items():
            idata = {
                "instance_id": inst.instance_id,
                "enemy_ref": inst.enemy_ref,
                "scene": inst.scene,
                "quantity": inst.quantity,
                "status": inst.status,
                "hp": inst.hp,
                "multi_attack": inst.multi_attack,
                "damage_multipliers": inst.damage_multipliers,
                "dodge_bonus": inst.dodge_bonus,
                "special_rules": inst.special_rules,
                "phases": inst.phases,
            }
            if inst.boss_mechanics:
                idata["boss_mechanics"] = inst.boss_mechanics
            instances_dict[iid] = idata
        return {
            "instances": instances_dict,
            "combat_active": self._combat_active,
            "combat_enemies": self._combat_enemies,
        }

    @classmethod
    def from_dict(cls, data: dict, library: EnemyLibrary) -> "EnemyManager":
        mgr = cls(library)
        for iid, idata in data.get("instances", {}).items():
            lib_enemy = library.get(idata["enemy_ref"])
            if lib_enemy:
                flags = list(lib_enemy.flags)
                behavior = lib_enemy.combat_behavior
                desc = lib_enemy.description
                attrs = dict(lib_enemy.attributes)
                armor = lib_enemy.armor
                attacks = list(lib_enemy.attacks)
                abilities = list(lib_enemy.special_abilities)
                san = lib_enemy.san_loss
                boss_mech = idata.get("boss_mechanics", "")
                base_hp = (attrs.get("CON", 50) + attrs.get("SIZ", 50)) // 10 * idata.get("quantity", 1)
                hp = idata.get("hp", base_hp)
            else:
                flags, behavior, desc = [], "", ""
                attrs, armor, attacks, abilities, san = {}, "", [], [], ""
                boss_mech = ""
                hp = 10
            mgr._instances[iid] = EnemyInstance(
                instance_id=idata["instance_id"],
                enemy_ref=idata["enemy_ref"],
                scene=idata["scene"],
                quantity=idata.get("quantity", 1),
                status=idata.get("status", "neutral"),
                flags=flags,
                combat_behavior=behavior,
                description=desc,
                attributes=attrs,
                armor=armor,
                attacks=attacks,
                special_abilities=abilities,
                san_loss=san,
                hp=hp,
                boss_mechanics=boss_mech,
                multi_attack=idata.get("multi_attack", 1),
                damage_multipliers=idata.get("damage_multipliers", {}),
                dodge_bonus=idata.get("dodge_bonus", 0),
                special_rules=idata.get("special_rules", ""),
                phases=idata.get("phases", []),
            )
        mgr._combat_active = data.get("combat_active", False)
        mgr._combat_enemies = data.get("combat_enemies", [])
        return mgr

    def __repr__(self):
        return f"EnemyManager({len(self._instances)} instances, combat={'on' if self._combat_active else 'off'})"
