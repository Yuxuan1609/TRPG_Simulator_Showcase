from __future__ import annotations
from game.messages import CombatInit
from library.bosses import BossLibrary


class BossManager:
    def __init__(self, boss_library: BossLibrary, boss_encounters: list[dict]):
        self._library = boss_library
        self._encounters = boss_encounters
        self._active_boss_id: str | None = None
        self._spawned_boss_ids: set[str] = set()  # 已生成的 Boss entity ID，防止重复生成

    def has_spawned(self, boss_id: str) -> bool:
        return boss_id in self._spawned_boss_ids

    def mark_spawned(self, boss_id: str) -> None:
        self._spawned_boss_ids.add(boss_id)

    def check_by_engage_type(self, engage_type: str, *, scene: str | None = None) -> list[dict]:
        results = []
        for enc in self._encounters:
            if enc.get("engage_type") != engage_type:
                continue
            if engage_type in ("at", "interaction") and scene is not None:
                if enc.get("scene") != scene:
                    continue
            results.append(enc)
        return results

    def build_combat_init(self, boss_entity: dict, player, scene: str) -> CombatInit:
        from game.enemy_manager import EnemyInstance
        import uuid

        boss_ref = boss_entity["boss_ref"]
        lib_boss = self._library.get(boss_ref)
        if not lib_boss:
            raise KeyError(f"Boss '{boss_ref}' not found in boss library")

        attrs = lib_boss.attributes
        base_hp = (attrs.get("CON", 100) + attrs.get("SIZ", 100)) // 10

        enemy = EnemyInstance(
            instance_id=f"{boss_ref}_{uuid.uuid4().hex[:8]}",
            enemy_ref=boss_ref,
            scene=scene,
            quantity=1,
            status="hostile",
            flags=list(lib_boss.flags),
            combat_behavior=lib_boss.boss_mechanics,
            description=lib_boss.description,
            attributes=dict(attrs),
            armor=lib_boss.armor,
            attacks=list(lib_boss.attacks),
            special_abilities=list(lib_boss.special_abilities),
            san_loss=lib_boss.san_loss,
            hp=base_hp,
            boss_mechanics=lib_boss.boss_mechanics,
            multi_attack=getattr(lib_boss, 'multi_attack', 1),
            damage_multipliers=dict(getattr(lib_boss, 'damage_multipliers', {})),
            dodge_bonus=getattr(lib_boss, 'dodge_bonus', 0),
            special_rules=getattr(lib_boss, 'special_rules', ''),
            phases=list(getattr(lib_boss, 'phases', [])),
        )

        return CombatInit(
            enemies=[enemy],
            player=player,
            scene=scene,
            initiative_context=boss_entity.get("description", ""),
        )

    @property
    def active_boss_id(self) -> str | None:
        return self._active_boss_id

    @active_boss_id.setter
    def active_boss_id(self, value: str | None):
        self._active_boss_id = value

    @property
    def library(self):
        return self._library

    def set_active(self, boss_id: str | None):
        self.active_boss_id = boss_id

    def resolve_outcome(self, combat_result):
        if not self._active_boss_id:
            return None
        return combat_result.outcome

    def active_snapshot(self) -> dict | None:
        """Return active boss info for world snapshot, or None."""
        if not self._active_boss_id:
            return None
        for enc in self._encounters:
            if enc.get("id") == self._active_boss_id:
                lib_boss = self._library.get(enc.get("boss_ref", ""))
                return {
                    "entity_id": self._active_boss_id,
                    "boss_ref": enc.get("boss_ref", ""),
                    "engage_type": enc.get("engage_type", ""),
                    "mechanics": lib_boss.boss_mechanics if lib_boss else "",
                }
        return None

    def to_dict(self) -> dict:
        return {
            "active_boss_id": self._active_boss_id,
            "encounters": self._encounters,
            "spawned_boss_ids": list(self._spawned_boss_ids),
        }

    @classmethod
    def from_dict(cls, data: dict, boss_library: BossLibrary) -> "BossManager":
        mgr = cls(boss_library, data.get("encounters", []))
        mgr._active_boss_id = data.get("active_boss_id")
        mgr._spawned_boss_ids = set(data.get("spawned_boss_ids", []))
        return mgr
