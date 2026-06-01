"""Message types for inter-agent communication."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from investigator.models import Investigator


@dataclass
class IntentResult:
    """Detector output — does the player's 'other' action carry narrative intent?"""
    needs_author: bool
    intent: str = ""          # one-line: what the player wants to accomplish
    reasoning: str = ""       # why this warrants escalation


@dataclass
class AuthorRequest:
    """Detector -> Author: player intent worth acting on."""
    other_texts: list[str] = field(default_factory=list)  # original "other" entry text(s)
    intent: str = ""            # Detector output
    reasoning: str = ""         # Detector output
    scene_context: dict = field(default_factory=dict)  # Keeper extracts from world


@dataclass
class ActionIntent:
    """Parsed player intent from step 1 (LLM parse)."""
    action: str                      # "move" | "interact" | "search" | "other"
    target: str = ""                 # target scene (move) or interaction name (interact)
    skill_checks: list[str] = field(default_factory=list)
    reasoning: str = ""
    condition: str = ""              # non-empty when player tries unmet interaction


@dataclass
class ActionOutcome:
    """Result of executing one action."""
    intent: ActionIntent
    success: bool
    message: str                     # human-readable result (resolved ##GRADED## if applicable)
    entity_id: str = ""              # which entity was executed ("I1", "AT3", etc.)
    entity_type: str = ""            # "interaction" | "auto_trigger" | "event"
    side_effects: list[Any] = field(default_factory=list)
    skill_tier: str = ""             # COC 7th tier: "" | "failure" | "regular" | "hard" | "extreme"
    skill_detail: str = ""           # raw dice result e.g. "侦查检定：D100=45/50"
    enhancement: dict | None = None  # trait enhancement result: {"tier","reason","detail_override"}


@dataclass
class SceneSnapshot:
    """Deterministic scene info for Narrator curation."""
    location: str
    description: str
    exits: list[dict]                # [{"target": "...", "method": "..."}]
    perceptible_interactions: list[str]  # names of available interactions
    visible_npcs: list[dict]         # [{"name": "...", "brief": "...", "demeanor": "..."}]


@dataclass
class NarratorBrief:
    """KP -> Narrator: curated ruling for narrative generation."""
    action_outcomes: list[ActionOutcome]
    ambient_changes: list[str]       # AT results perceptible to player
    scene_snapshot: SceneSnapshot
    suggested_emphasis: str          # what to highlight + tone direction


@dataclass
class ModulePatch:
    """Author -> KP: persistent entity additions."""
    entities: list[dict]             # new entities in L2 dict format
    scene_descriptions: dict[str, str]  # scene_name -> updated description
    justification: str = ""


@dataclass
class StructuralEdit:
    """Author -> Keeper: structural expansion needed. Triggers supplement pipeline."""
    supplement_path: str = ""       # supplements/<timestamp>/
    l3_updates: dict = field(default_factory=dict)
    entry_scene: str = ""
    exit_scene: str = ""
    justification: str = ""


@dataclass
class TurnInput:
    """Entry point input."""
    raw_text: str
    player: Any | None = None  # Investigator | None


@dataclass
class CombatEntryCheck:
    """Combat entry detection result from LLM."""
    enter_combat: bool
    enemy_instance_ids: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class StandoffMatch:
    """Semantic match result for standoff phase."""
    matched: bool
    skill_name: str = ""
    reason: str = ""


@dataclass
class CombatInit:
    """Passed to pluggable combat system when combat begins."""
    enemies: list[Any] = field(default_factory=list)
    player: Any = None
    scene: str = ""
    initiative_context: str = ""
    environment_actions: list[dict] = field(default_factory=list)
    player_action: str = ""
    player_targets: list[str] = field(default_factory=list)
    player_extra: str = ""

    MAX_ENEMIES: int = field(default=5, init=False, repr=False)

    def __post_init__(self):
        if len(self.enemies) > self.MAX_ENEMIES:
            self.enemies = self.enemies[:self.MAX_ENEMIES]


@dataclass
class CombatResult:
    """Returned by combat system when combat ends."""
    outcome: str = ""              # "win" | "loss" | "flee"
    defeated_instance_ids: list[str] = field(default_factory=list)
    narrative: str = ""            # combat summary narrative
    player_hp: int = 0
    player_san: int = 0
    rounds: int = 0
    round_log: list[Any] = field(default_factory=list)


@dataclass
class SkillCheckResult:
    """A single skill check — original D100 roll + optional LLM enhancement."""
    entity_id: str = ""
    entity_type: str = ""       # "interaction" | "auto_trigger" | "event"
    skill_name: str = ""        # e.g. "侦查"
    raw_roll: int = 0           # original D100 result
    target: int = 0             # skill value / threshold
    tier: str = ""              # "" | "failure" | "regular" | "hard" | "extreme"
    success: bool = False
    enhancement: dict | None = None  # trait enhancement {"tier", "reason", "detail_override"}


@dataclass
class PlayerFacingSnapshot:
    """Unified player-facing supplementary info — returned alongside Narrator narrative.

    Distinct from SceneSnapshot (feeds Narrator curation) and world.build_snapshot()
    (feeds prompt builders). PlayerFacingSnapshot is the final output for the player/UI.
    """
    scene_name: str = ""
    scene_description: str = ""        # L1 immersive third-person description
    exits: list[dict] = field(default_factory=list)  # [{"target":"...","method":"..."}]
    time: dict = field(default_factory=dict)          # {"game_time": 0, "time_context": ""}
    npcs: list[dict] = field(default_factory=list)    # [{"name":"...","brief":"...","demeanor":"..."}]
    enemies: list[dict] = field(default_factory=list)  # [{"enemy_ref":"...","status":"...","quantity":1}]
    combat: dict | None = None         # {"outcome","narrative","is_boss"} or None
    skill_checks: list[SkillCheckResult] = field(default_factory=list)
    investigator: Optional[Investigator] = None  # 调查员对象，可读取 weapons / item_manager


@dataclass
class RoundResult:
    """Single round result, shared between deterministic layer and LLM correction."""
    round: int = 0
    player_action: str = ""
    player_target: str = ""
    player_roll: int = 0
    player_tier: str = ""
    player_damage: int = 0
    player_damage_type: str = "物理"
    player_effects: list[str] = field(default_factory=list)
    enemy_actions: list[dict] = field(default_factory=list)
    status_changes: list[dict] = field(default_factory=list)
    narrative: str = ""


@dataclass
class Phase:
    """Boss phase definition."""
    trigger: str = ""         # "hp_below_pct:0.5" | "round:3"
    name: str = ""
    overrides: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class TimeCommsPacket:
    """Keeper -> Author: time pressure communication packet. ≤500 chars total."""
    game_time: int = 0
    day: int = 0
    time_of_day: str = ""
    current_scene: str = ""
    player_actions: str = ""   # recent actions summary (≤200 chars)
    world_state: str = ""      # world state overview (≤200 chars)


@dataclass
class PreParseResult:
    """Pre-parse disambiguator output."""
    clarity: str = ""          # "clear" | "ambiguous"
    interpretation: str = ""   # one-line interpretation of player intent
    question: str = ""         # clarifying question (with 1-2 examples) when ambiguous
    resolved_text: str = ""    # integrated text for Parse (e.g. "搜一下抽屉") when clear with context


@dataclass
class EnrichInput:
    """Typed intermediate structure for parse→enrich→curate pipeline (O8).

    Replaces bare list[dict] for judged_entities and action_summaries.
    """
    entities: list[dict] = field(default_factory=list)  # judged entity records
    actions: list[dict] = field(default_factory=list)    # TimeAgent action summaries
