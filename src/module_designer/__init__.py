"""三层信息引擎."""
from module_designer.l1_player import SceneL1, Perceptible, NPCAppearance, load_l1, save_l1
from module_designer.l2_keeper import (
    SceneL2, Encounter, SceneWeapon, AutoTrigger, NPCProfile, load_l2, save_l2,
)
# NPCProfile is an alias for game.npc_manager.NPC (maintained for backward compat)
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, CharacterDesign,
    SceneIntent, EndingCondition, ToneConstraints, load_l3, save_l3,
)
from module_designer.layered_schema import (
    validate_l1, validate_l2, validate_l3, validate_all, is_valid,
    SchemaReport, SchemaViolation,
)
from module_designer.layered_parser import (
    parse_step1a, parse_step1b,
    build_step1a_prompt, build_step1b_prompt,
    build_step2a_prompt, build_step2b_combined_prompt,
    build_step2c_l1_prompt, build_step2c_l3_prompt,
    build_step3a_prompt, build_step35_prompt,
    build_phase1_prompt, build_step4_prompt,
    build_step2_boss_prompt, parse_step2_boss,
    parse_step25_combined,
    _with_fallback, _is_valid_json_output,
)
from module_designer.dependency_graph import (
    DependencyGraph, DependencyNode, DependencyEdge,
)
from module_designer.layered_pipeline import (
    run_pipeline, cross_validate_layers, PipelineResult,
    CrossRefReport, CrossRefIssue, save_pipeline_result,
    _bind_npc_entities, _assemble_l2, _inject_npc_special_entities,
)
