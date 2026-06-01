# Requirement & Clue System — Design Spec

**Date**: 2026-05-06
**Context**: `scene_output_resolved_revised.json` and `res_event_resolved_revised.json` introduce `requirement` (prerequisite chains) and `clue` (nullable hints) fields. The engine must validate prerequisites before executing interactions/events and surface missing conditions to the player.

---

## 1. Data Model

### 1.1 New `Requirement` dataclass

```python
@dataclass
class Requirement:
    ref_type: str      # "interaction" | "event" | "flag"
    ref_scene: str     # scene ID (e.g. "4号车厢")
    ref_name: str      # prerequisite name (e.g. "急救乘务员")
```

### 1.2 Updated `Interaction`

| Field | Type | Change |
|-------|------|--------|
| `type` | `str` | unchanged |
| `name` | `str` | unchanged |
| `trigger` | `str` | unchanged |
| `result` | `str` | unchanged |
| `clue` | `Optional[str]` | was `str`, now `Optional[str]` (JSON has `null`) |
| `requirements` | `List[Requirement]` | **NEW** — defaults to `[]` |

### 1.3 Updated `GameEvent`

| Field | Type | Change |
|-------|------|--------|
| `event_id` | `str` | unchanged |
| `name` | `str` | unchanged |
| `trigger` | `str` | unchanged |
| `impact` | `str` | unchanged (maps from `irreversible_impact` key in JSON) |
| `requirements` | `List[Requirement]` | **NEW** — defaults to `[]` |

---

## 2. Requirement Resolution

### 2.1 `RequirementResolver` class

Owned by `ScenarioWorld`. Checks requirements against world state.

**`check(requirements) -> Tuple[bool, str]`**
- Iterates all requirements. For each `ref_type`:
  - `"interaction"` → `completed_interactions[ref_scene]` contains `ref_name`
  - `"event"` → `triggered_events[ref_event_id]` is `True`
  - `"flag"` → `flags[ref_flag_name]` is `True`
- Returns `(True, "")` if all pass.
- On first unmet requirement, returns `(False, "需要先完成「{ref_scene}」的「{ref_name}」")`.

**`get_unmet(requirements) -> List[Requirement]`**
- Returns the subset of requirements not yet satisfied.

**`resolve_chain(requirements) -> List[Requirement]`** _(stub — deferred)_
- Will walk transitive dependencies to find the root unmet prerequisite. Left as a placeholder for future campaigns with deeper chains.

### 2.2 Integration points

| Method | Change |
|--------|--------|
| `execute_interaction(name)` | Prepend `resolver.check(interaction.requirements)`, return `(False, msg)` on failure |
| `trigger_event(event_id)` | Same pattern before existing guards |
| `get_available_interactions()` | Append `[需要前置]` to name when requirements unmet |
| `get_scene_info()` | Add `clue` and `requirements_met: bool` to interaction dicts |

---

## 3. DirectedGraph Parsing

### `load_scenes(data)`
- Parse `requirement` list from each interaction JSON entry into `List[Requirement]`
- Pass `inter.get("clue")` as-is (nullable)

### `load_events(data)`
- Parse `requirement` list from each event JSON entry into `List[Requirement]`
- Continue reading both `irreversible_impact` and `impact` keys for backward compatibility

---

## 4. Notebook Changes (`notebook_simplified.ipynb`)

| Location | Change |
|----------|--------|
| `run_game()` file paths | `scene_output_revised.json` → `scene_output_resolved_revised.json`, `res_event_revised.json` → `res_event_resolved_revised.json` |
| `_build_scene_context()` | Include `[需要前置]` suffix on gated interactions |
| `handle_user_input()` | No logic change needed — `execute_interaction` already returns failure message with missing prerequisite; LLM narrates it naturally |

---

## 5. Files Modified

- `scenario_core.py` — all dataclass/model/logic changes (~60-80 lines added/changed)
- `notebook_simplified.ipynb` — file paths + prompt builder enhancement (~3 cells changed)

## 6. Verification

1. Run `python scenario_core.py` — no import/syntax errors
2. In notebook: load the `_resolved_revised` files, verify graph builds with requirements populated
3. Execute an interaction with unmet requirement → expect `(False, "需要先完成「X」的「Y」")`
4. Execute its prerequisite → expect `(True, ...)`
5. Re-execute the previously-blocked interaction → expect `(True, ...)`
6. Repeat steps 3-5 for `trigger_event` with event requirements (E4)
7. Check `get_scene_info()` output includes `clue` and requirement state
