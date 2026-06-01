# 模组运行 — Spec 索引

在线流程：三层 JSON → DirectedGraph → ScenarioWorld → Game Loop → LLM 叙事。

## 核心文档

| 文档 | 内容 | 状态 |
|------|------|------|
| [`../2026-05-06-requirement-system-design.md`](../2026-05-06-requirement-system-design.md) | 前置条件系统设计 | 已实现 |
| [`../2026-05-07-game-loop-refactor-design.md`](../2026-05-07-game-loop-refactor-design.md) | Game Loop 重构：三阶段 LLM 调用链 | 已实现 |
| [`../2026-05-07-multi-action-design.md`](../2026-05-07-multi-action-design.md) | 多动作识别设计 | 已实现 |
| [`../2026-05-08-triggerable-separation-design.md`](../2026-05-08-triggerable-separation-design.md) | 可触发/不可触发事件分离 | 已实现 |
| [`../2026-05-09-coc-character-builder-design.md`](../2026-05-09-coc-character-builder-design.md) | COC 7th 车卡系统设计 | 已实现 |
| [`../2026-05-11-optimization-analysis.md`](../2026-05-11-optimization-analysis.md) | 优化分析 | 分析完成 |
| [`../2026-05-11-skill-check-overhaul-design.md`](../2026-05-11-skill-check-overhaul-design.md) | 技能检定 overhaul | 已实现 |
| [`../2026-05-11-call-deepseek-params-design.md`](../2026-05-11-call-deepseek-params-design.md) | DeepSeek 调用参数设计 | 已实现 |
| [`../2026-05-12-interaction-event-serialization-design.md`](../2026-05-12-interaction-event-serialization-design.md) | Interaction/Event 序列化设计 | 已实现 |
| [`../2026-05-12-modification-summary.md`](../2026-05-12-modification-summary.md) | 修改总结 | 参考 |
| [`../2026-05-12-parser-modification-briefing.md`](../2026-05-12-parser-modification-briefing.md) | Parser 修改简报 | 参考 |

## 实现状态

| 模块 | 文件 | 状态 |
|------|------|------|
| 场景核心 | `src/scenario_core.py` | ✓ 已实现 (含全部 7 种 side effect + npc_states) |
| LLM 调用 | `src/llm.py` | ✓ 已实现 |
| Prompt 构建 | `src/prompts.py` | ✓ 已实现 (L1/L3 上下文已写但未接通) |
| Game Loop | `src/game_loop.py` | ✓ 已实现 (/spawn 命令, Phase 3.5 桩) |
| 调查员系统 | `src/investigator/` | ✓ 已实现 |
| 武器/敌人库 (运行时) | `src/library/` | ✓ judgment.py + injector.py 可用于运行时 |
| L2 数据模型 | `src/module_designer/l2_keeper.py` | ✓ HiddenInfo → AutoTrigger (含 effect_type) |
| 显示组件 | `src/trpg_display.py` | ✓ 已实现 |

## 已知断点 (P0)

| # | 问题 | 位置 |
|---|------|------|
| C1 | `Interaction` 缺少 `skill_name`/`difficulty` 字段 — LLM 生成的技能信息被丢弃 | `scenario_core.py:47-56` |
| C2 | L1/L3 数据未加载到 notebook — `_build_l1l3_context` 永远返回空 | `notebook_simplified.ipynb` |
| C3 | `_check_deviation` 桩永远返回 0.0 | `game_loop.py:167-173` |
| C4 | `EncounterAnchor` 定义但未使用 | `scenario_core.py:101-108` |
| C5 | auto_trigger 被动检测逻辑未实现 (依赖 parser Step 4b) | `game_loop.py`, `scenario_core.py` |

## 生成端 → 运行端的数据接口

当前: `l2_keeper.json` → `l2["scenes"]` → `DirectedGraph(scenes=...)`, `l2["events"]` → `DirectedGraph(events=...)`

待接通: L1/L3 JSON → notebook → `handle_user_input(l1_data=..., l3_data=...)` → `build_narrative_prompt(l1_scene=..., l3_data=...)`
