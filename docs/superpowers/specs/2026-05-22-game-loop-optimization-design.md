# Game Loop Optimization — Keeper cleanup + unified world snapshot

Date: 2026-05-22
Status: design
Scope: `src/game_loop.py`, `src/game/agents/keeper.py`, `src/prompts.py`, `src/scenario_core.py`, `src/investigator/models.py`

## Motivation

After the ScenarioWorld refactor (Facade + 5 subsystems), the game loop has two structural problems:

1. **Duplicate subsystem instances**: `init_game` creates `boss_manager`/`npc_manager`, but `ScenarioWorld.__init__` creates its own (empty) `self.bosses`/`self.npcs`. Keeper gets the properly-initialized ones from `init_game`; World's copies are unused and empty.

2. **Fragmented context assembly**: Seven different functions each assemble their own partial view of world state, with inconsistent field names and missing data (no player weapons/stats, no scene enemies, no time context in parse prompt).

## Phase 1: Remove Keeper duplicate state

### ScenarioWorld: accept fully-initialized subsystems

`ScenarioWorld.__init__` gains `npc_profiles` and `boss_library`/`boss_encounters` params so it can properly initialize its own subsystems:

```python
def __init__(self, graph, start_node, *,
             background_story="", wr0_enabled=False,
             enemy_library=None, weapon_library=None,
             boss_library=None, boss_encounters=None,
             npc_profiles=None):
    ...
    self.npcs = NPCManager()
    if npc_profiles:
        self.npcs.init_from_profiles(npc_profiles)
    self.bosses = BossManager(boss_library, boss_encounters or []) if boss_library else None
```

### Keeper: remove duplicate params

Keeper drops `dependency_graph`, `npc_profiles`, `boss_manager`, `npc_manager`, `time_costs`, `comms_interval`. Everything routes through `self.world.*`:

| Before (Keeper attr) | After (World attr) |
|---|---|
| `self.dependency_graph` | `self.world.dependency_graph` |
| `self.boss_manager` | `self.world.bosses` |
| `self.npc_manager` | `self.world.npcs` |
| `self.time_costs` | `self.world.time_costs` |
| `self.comms_interval` | `self.world.comms_interval` |
| `self.npc_profiles` | (removed — not used directly by Keeper) |

`_last_comms_time` and `_last_ta_call` stay on Keeper (orchestration state, not world state).

### init_game: single source of truth

- Pass `boss_library`, `boss_encounters`, `npc_profiles` to `ScenarioWorld`
- NPC scene-assignment logic stays in `init_game` (L2-specific)
- `game` dict drops `boss_manager`/`npc_manager` keys — consumers go through `keeper.world`

### apply_side_effects: fix backward-compat pattern

`scenario_core.py:1123`: `hasattr(world, 'npc_manager')` → `world.npcs`

## Phase 2: Unified world snapshot

### Investigator.build_snapshot()

New method on `Investigator` (`src/investigator/models.py`):

```python
def build_snapshot(self) -> dict:
    """Return a lightweight dict of player state for prompt contexts."""
    return {
        "name": self.name,
        "hp": self.derived.HP,
        "san": self.derived.SAN,
        "mp": self.derived.MP,
        "weapons": [w.name for w in self.weapons],
        "inventory": self.item_manager.describe() if hasattr(self, 'item_manager') else "",
        "skills_summary": ", ".join(f"{s.name}={s.value}" for s in self.skills[:10]),
        "description": getattr(self, 'personal_description', '') or "",
    }
```

### ScenarioWorld.build_snapshot()

New method on `ScenarioWorld` — pure data assembly, no LLM:

```python
def build_snapshot(self) -> dict:
    return {
        "location": self.current_location,
        "description": self.get_current_description(),
        "exits": [{"target": e.target, "method": e.method} for e in self.get_possible_exits()],
        "time": self.clock.to_dict(),
        "player": self.player.build_snapshot() if self.player else {},
        "npcs_in_scene": self.npcs.get_in_scene_snapshot(self.current_location),
        "enemies_in_scene": self.enemies.get_active_in_scene_snapshot(self.current_location) if self.enemies else [],
        "boss_active": self.bosses.active_snapshot() if self.bosses else None,
        "scene_weapons": [
            {"weapon_ref": sw.weapon_ref, "quantity": sw.quantity}
            for sw in self.scene_weapons.get(self.current_location, [])
        ],
        "runtime": {
            "completed": [eid for eid, s in self.runtime_state.items() if s.completed],
            "triggered_events": [eid for eid, t in self.triggered_events.items() if t],
        },
    }
```

### Prompt builders: consume unified snapshot

Each prompt builder calls `world.build_snapshot()` and pulls the slice it needs. The current seven fragmented helpers collapse:

- `_build_scene_context()` — replaced by snapshot `location`/`description`/`exits`
- `_build_world_state()` — replaced by snapshot `runtime`
- `_build_investigator_info()` — replaced by snapshot `player`
- `_build_player_skills()` — replaced by snapshot `player.skills_summary`
- `_build_entity_lines()` — stays (entity listing is format-specific, not state)
- `keeper._build_world_snapshot()` — replaced by snapshot `location`/`npcs_in_scene`
- `keeper._build_scene_context_for_author()` — replaced by snapshot

Keeper's parse prompt gains: player weapons, HP/SAN, NPCs in scene, enemies in scene, time context.
Keeper's enrich prompt gains: player state, NPC/enemy presence.
Author/IntentDetector snapshots gain: time, enemies, player state.

### NPCManager / EnemyManager / BossManager: add snapshot helpers

- `NPCManager.get_in_scene_snapshot(scene) → list[dict]` — `[{name, state, attitude, following}]`
- `EnemyManager.get_active_in_scene_snapshot(scene) → list[dict]` — `[{enemy_ref, status, flags, quantity}]`
- `BossManager.active_snapshot() → dict | None` — `{name, mechanics}` if active boss

## Files touched

| File | Phase 1 | Phase 2 |
|------|---------|---------|
| `src/scenario_core.py` | `__init__` new params, fix `apply_side_effects` | `build_snapshot()` |
| `src/game_loop.py` | Pass subsystems to World, drop dict keys | — |
| `src/game/agents/keeper.py` | Remove 6 params, route through world | Replace fragmented snapshot builders |
| `src/prompts.py` | — | Refactor prompt builders to use unified snapshot |
| `src/investigator/models.py` | — | `build_snapshot()` |
| `src/game/npc_manager.py` | — | `get_in_scene_snapshot()` |
| `src/game/enemy_manager.py` | — | `get_active_in_scene_snapshot()` |
| `src/game/boss_manager.py` | — | `active_snapshot()` |

## Not in scope

- `npc_states` serialization bug in `to_dict`/`from_dict` — noted in README, separate fix
- TimeAgent functional changes
- Combat system changes
- NPC dialogue system changes
