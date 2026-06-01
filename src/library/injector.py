"""内容注入引擎 —— 离线预填充 + 运行时动态注入."""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from config import OFFLINE_INJECTION_ENABLED, RUNTIME_INJECTION_ENABLED

if TYPE_CHECKING:
    from library.weapons import WeaponLibrary
    from library.enemies import EnemyLibrary
    from scenario_core import ScenarioWorld


class ContentInjector:
    """
    从武器/敌人库向模组内容注入引用。
    - offline: 模组构建时，扫描 L3+L2 自动填充 encounter/weapon 引用
    - runtime: 游戏进行中，LLM 判断偏离时动态注入
    """

    def __init__(
        self,
        weapon_lib: "WeaponLibrary",
        enemy_lib: "EnemyLibrary",
        offline_enabled: bool = OFFLINE_INJECTION_ENABLED,
        runtime_enabled: bool = RUNTIME_INJECTION_ENABLED,
    ):
        self.weapons = weapon_lib
        self.enemies = enemy_lib
        self.offline_enabled = offline_enabled
        self.runtime_enabled = runtime_enabled

    # ── 离线注入 ──

    def offline_inject_scene(self, scene_data: dict, l3_scene_intent: dict = None) -> dict:
        """
        根据场景 L2 数据和 L3 scene_intent 自动填充 encounter/weapon 引用。
        当前为确定性规则版本（不需要 LLM）：
        - danger_level=high/extreme → 搜索匹配的敌人建议
        - 不对已有 encounter 做修改
        """
        if not self.offline_enabled:
            return scene_data

        if l3_scene_intent:
            danger = l3_scene_intent.get("danger_level", "safe")
            if danger in ("high", "extreme"):
                scene_data.setdefault("encounters", [])
                scene_data.setdefault("scene_weapons", [])

        return scene_data

    def offline_inject_module(self, l2_data: dict, l3_data: dict) -> dict:
        """对所有场景执行离线注入."""
        if not self.offline_enabled:
            return l2_data
        scene_intents = l3_data.get("scene_intents", {})
        for scene_name, scene_data in l2_data.get("scenes", {}).items():
            intent = scene_intents.get(scene_name)
            l2_data["scenes"][scene_name] = self.offline_inject_scene(scene_data, intent)
        return l2_data

    # ── 运行时注入 ──

    def runtime_spawn_enemy(
        self, enemy_name: str, scene_name: str, world: "ScenarioWorld" = None
    ) -> dict | None:
        """运行时动态生成敌人遭遇."""
        if not self.runtime_enabled:
            return None
        enemy = self.enemies.get(enemy_name)
        if not enemy:
            return None
        return {
            "enemy_ref": enemy_name,
            "trigger_condition": f"runtime_injection in {scene_name}",
            "initial_behavior": enemy.combat_behavior,
            "quantity": 1,
            "notes": "运行时动态注入",
        }

    def runtime_grant_weapon(self, weapon_name: str) -> dict | None:
        """运行时动态分发武器."""
        if not self.runtime_enabled:
            return None
        weapon = self.weapons.get(weapon_name)
        if not weapon:
            return None
        return {
            "weapon_ref": weapon_name,
            "location": "runtime_injection",
            "discovery_method": "动态注入",
        }

    @property
    def status(self) -> dict:
        return {
            "offline_enabled": self.offline_enabled,
            "runtime_enabled": self.runtime_enabled,
            "weapons_loaded": len(self.weapons),
            "enemies_loaded": len(self.enemies),
        }
