# Supplement Pipeline Redesign

## Overview

重写 `run_supplement_pipeline`，从 5 次 LLM 调用降为 4 次，叙事先行 → 并行生成 → 确定性校验。

## Input

```python
def run_supplement_pipeline(
    player_intent: str,        # Detector: 玩家想达成什么
    reasoning: str,            # Detector: 为什么需要 Author
    base_l3: dict,             # Author 持有的完整 L3
    entry_scene: str,          # Author: 入口场景
    exit_scene: str = "",      # Author: 出口场景（可被 Step 1 覆盖）
    world_snapshot: dict = {}, # 新增：Keeper._build_world_snapshot()
    output_dir: str = "",
    module_name: str = "",
) -> dict:
```

调用方 (`keeper._integrate_supplement`) 新增传入 `world_snapshot=self._build_world_snapshot()`。

## Pipeline Flow

### Step 1 — Narrative First (1 LLM call, flash+max)

**Input**: 完整 base_l3（world_rules / narrative_lines / tone_constraints / driving_force / scene_intents）+ world_snapshot + player_intent + reasoning + entry/exit

**Output**:
- `story`: 一段模组风格叙事文字，描述 1-3 个新场景的展开
- `exit_scene`: 确认/重定的出口场景
- `scene_names`: 标准化场景名清单 `["SS1_镜中世界", "SS2_深渊回廊"]`

### Step 2 — Parallel Generation (3 parallel LLM calls, flash+max)

**2a — Entities**: 所有场景的 interactions + auto_triggers + events + scene_movements + dependency_graph。内联 @markup 标准化（无需单独步骤）。参考主管线 Step 2a entity 格式文档 + Step 3 去重/一致性规则。

**2b — L1**: 新场景的 description / atmosphere / mood / perceptible / ambient_hints / npc_appearances

**2c — L3**: 新场景的 scene_intents（purpose / key_threat / notes），可能的 world_rules/tone_constraints 局部调整

### Post-Generation — Deterministic

- 组装 L2：将 Step 2a 输出的 entities 按场景分组，构造 `{scenes, events, dependency_graph, _scene_names, _phase1}` 结构
- 校验：循环检测 (dependency_graph)、entity ID 唯一性、scene 引用完整性、graded_result 与 type 一致性
- 写入 l1_supp/l2_supp/l3_supp JSON

## LLM Call Summary

| Step | Calls | Model | Reasoning |
|------|-------|-------|-----------|
| Step 1 | 1 | flash | max |
| Step 2a | 1 | flash | max |
| Step 2b | 1 | flash | max |
| Step 2c | 1 | flash | max |
| **Total** | **4** | | |

旧管线: 5 calls (1a/1b/1c parallel + assemble/standardize parallel)

## Key Changes from Old Pipeline

| Aspect | Old | New |
|--------|-----|-----|
| Step 1 | 3 parallel (scenes/events/L1) | 1 call, narrative-driven |
| @markup | Separate LLM call | Inline in Step 2a |
| L3 | Deterministic inherit | LLM-generated per scene |
| Validation | None | Schema check |
| world_snapshot | Not used | Passed to Step 1 |
| exit_scene | Read-only | Step 1 confirms/overrides |

## Integration Points

- `keeper._integrate_supplement`: add `world_snapshot=self._build_world_snapshot()` to `run_supplement_pipeline` call
- `keeper._build_world_snapshot`: already returns `{location, scene_description, npc_states}`, compatible
- Test: `test_escalation_harness.py` Case E mock `_mock_pipeline` signature gains `world_snapshot` param
