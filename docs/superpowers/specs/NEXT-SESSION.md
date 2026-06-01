# Next Session — 当前状态 + 待办

**日期**: 2026-05-22
**分支**: main
**状态**: 时间系统实现 | 战斗全链路打通 | NPC 统一管理 | O1-O3 已解决 | 7 @markup 全覆盖 | 提示词全面修正 | 149 测试 pass

---

## 当前架构

```
玩家输入 → Parse(LLM) → Judge(确定) → Enrich(LLM) ∥ IntentDetect(LLM) ∥ CombatEntryDetect(LLM) → [对峙] → Curate → Narrate(LLM) → 输出
                                                                         ↓ (other+有意义)                         ↓ (enter_combat+avoidable)
                                                                   Author(LLM)                           Standoff(语义匹配→D100→特质修正)
                                                                   ├─ Patch → integrate → 递归              ├─ 成功 → neutral/绕过 → 正常流程
                                                                   ├─ Structural → 补充管线 → integrate     └─ 失败 → CombatInit → 战斗系统(TODO)
                                                                   └─ Reject → 注入提示 → 正常流程
```

### Agent

| Agent | 数据 | 职责 |
|-------|------|------|
| Keeper | L2 + ScenarioWorld | 回合编配: parse→judge→enrich∥detect∥combat_entry→standoff→curate |
| Narrator | L1 | 唯一面向玩家，沉浸式叙事 |
| Author | L3 | 两级响应: Patch(填缺口) / StructuralEdit(触发补充管线)，WR0 独立可配 |
| IntentDetector | — | Parse 命中 other 时并行检测是否存在实际叙事意图 |
| EnemyManager | EnemyLibrary + EnemyInstance | 纯追踪层：敌人实例管理、位置/状态/flag 查询、combat entry 上下文构建 |

### 关键机制
- **dependency_graph + runtime_state**: 替代 world.flags，静态依赖 + 动态状态两层
- **parse_hard_requirement**: AND/OR 结构化解析，edge AND 兜底
- **@markup**: 6 种（spawn_enemy/grant_weapon/stat_change/item_gain/consume_item/npc_state_change），运行时解析
- **##GRADED##**: COC 7th D100 四级检定 (failure/regular/hard/extreme)
- **失败惩罚**: 难度升级 → LLM 创意后果
- **特质修正**: trait enhancement sub-agent（search、standoff、combat 等所有检定后统一调用）
- **LLM 错误提示**: 各阶段有玩家可见警告
- **Combat entry 检测**: 确定性闸门（active enemy in range）→ LLM 判定（与 enrich 并行）→ CombatEntryCheck
- **[flag] 标记**: enemies.json 的 combat_behavior 前缀，2 种：[adjacent_aware]（跨场景感知）、[avoidable]（可非战斗绕过）
- **对峙阶段**: avoidable 敌人 → 语义匹配 LLM → D100 技能检定 → 特质修正 → 成功转 neutral / 失败进战斗
- **EnemyManager 追踪层**: 纯状态管理（neutral/hostile/dead），战斗系统消费者，enter_combat/exit_combat 回调
- **时间系统**: 分钟制时钟（game_time→day/hour/time_of_day 自动推导）→ TimeAgent (LLM 叙事引导) ∥ Author.assess_time_pressure (通信包调度) → time_context 注入 enrich/narrator prompt
- **NPC 统一管理**: NPCManager 全量管理（对话/态度/跟随/状态），@npc_state_change & @npc_follow 均路由至 NPCManager.set_state/set_following，npc_profiles 含 initial_state/attitude/following
- **武器获取系统**: grant_weapon → scene_weapons → search 发现 → 确认拾取 → Investigator.add_weapon → 场景移除
- **属性变化系统**: stat_change → Investigator.modify_stat (delta/dice formula) + LLM narrative 更新描述
- **物品管理**: ItemManager，item_gain(quantity) → 背包加入，consume_item → 严格匹配 → LLM 模糊匹配保底

### 当前使用文件

**测试环境**: `data/modules/常暗之厢/l*_test.json`（测试房间 + 原模组内容）
**正式环境**: `data/modules/常暗之厢/l*_keeper/player/designer.json`

---

## 待实现 / 进行中

### 1. 作者介入机制 (Author Escalation) — 需明确

**当前状态**: 骨架已实现。`_check_escalation` 每回合 LLM 评估，`Author.handle_escalation` 生成 ModulePatch。
**待明确**:
- Escalation 触发条件是否足够精准（目前用 LLM 评估维度 + 阈值）
- ModulePatch 如何回注到 game world（`_integrate_patch` 已预留接口，需验证完整链路）
- 创作者豁免 WR0 如何在实际裁决中体现
**代码位置**: `src/game/agents/keeper.py:154-161`, `src/game/agents/author.py`, `src/game/escalation.py`

### 2. 战斗系统 — 进入/脱出已打通，战斗回合 TODO

**已完成** (2026-05-20):
- `[flag]` 标记解析：`[adjacent_aware]`（跨场景感知）、`[avoidable]`（可非战斗绕过），从 enemies.json 的 combat_behavior 前缀提取
- `EnemyManager` 追踪层：`SpawnEnemy` 真正实例化 EnemyInstance，追踪位置/状态/flag，提供 combat context
- Combat entry 检测：确定性闸门（active enemy in range）→ LLM 判定（flash，与 enrich 并行）→ `CombatEntryCheck`
- 对峙阶段：avoidable 敌人 → 语义匹配 LLM → D100 技能检定 → trait enhancement → 成功转 neutral / 失败进战斗
- 脱出回调：`EnemyManager.exit_combat(result)` — defeated→dead, survivors→hostile, combat_active=False
- 新增 15 个确定性测试（9 enemy_manager + 6 integration），全 pass

**设计文档**: `docs/superpowers/specs/2026-05-19-combat-entry-detection-design.md`

**待实现 — 战斗系统本体**:
- COC 7th 回合制战斗核心（先攻 → 行动 → 伤害 → 状态）
- 敌人 AI
- 与现有 skill check 系统的衔接（格斗、射击等技能已有 D100 检定能力）
- 战斗系统通过 `CombatInit` 接收数据，返回 `CombatResult` → EnemyManager.exit_combat()

**代码位置**: `src/game/enemy_manager.py`（EnemyManager）, `src/game/agents/keeper.py`（combat entry + standoff）, `src/library/enemies.py`（LibraryEnemy+flags）, `src/game/messages.py`（CombatEntryCheck/CombatInit/StandoffMatch）

### 3. NPC / 同伴系统 — TODO

**目标**: NPC 主动行为、对话树、状态驱动反应
**当前状态**: L2 有 `npc_profiles`（what_they_can_do, interaction_triggers, personality_notes），`NPCStateChange` 可修改状态。但 NPC 完全被动——仅在玩家触发 interaction 时反应。
**待实现**:
- NPC 主动推进剧情（基于时间/玩家位置/事件触发）
- 对话系统（tree 或 freeform + LLM？）
- 同伴跟随机制（已留下接口 I11 背负乘务员）
- NPC 对玩家行为的情绪/态度变化
**代码位置**: `data/modules/常暗之厢/l2_keeper.json` → `npc_profiles`

### 4. 时间系统 — TODO

设计文档已完成: `docs/superpowers/specs/2026-05-19-time-system-design.md`
**方案**: 两层架构 — 确定性世界时间 + TimeAgent (LLM sub-agent)
**待实现**:
- `ScenarioWorld` 加 `game_time`/`time_of_day`/`time_context`
- `TimeAgent` 类（flash 模型，每 2-3 回合触发）
- L3 `countdowns` 字段
- Entity `extra.time_cost`/`extra.time_gated`
- Prompt 时间上下文注入

### 5. 测试文件说明

当前有三套测试：

**Game Loop Harness** (`tests/game_loop_harness.py`) — 7 轮真实 LLM 调用，/scene /char /save /load 等。完整 prompt/response 日志，输出到 `data/debug/test_harness/<ts>/`

**Author Flow 单元测试** (`tests/test_author_flow.py` + `tests/test_intent_detector.py`) — 11 个测试，全部 LLM mock，覆盖：Detector (flavor/有意义/空输入)、Author flow (零开销 / flavor不触发 / Patch集成 / Reject注入 / 重复抑制 / 字段完整性 / Supplement集成 / Scene context)

**Escalation Harness** (`tests/test_escalation_harness.py`) — 4 个 case (正常匹配 / flavor / Patch / Reject)，基于常暗之厢场景，Author prompt+response 日志输出到 `data/debug/test_escalation/<ts>/`

测试数据：`data/modules/常暗之厢/l*_test.json`（测试房间 + 原模组内容）。`start_node` 已切到「测试房间」。

---

## 已知缺口 (更新于 2026-05-19)

| # | 问题 | 状态 |
|---|------|------|
| G1 | Judge 需求检查仅 `flag:` 前缀 | FIXED — dependency_graph + runtime_state + parse_hard_requirement |
| G2 | `from_dict` 未更新 Entity 格式 | FIXED — _are_requirements_met 使用 parse_hard_requirement; runtime_state/dependency_graph 纳入 save/load 往返; 移除 dead code _parse_side_effects; Entity 添加 summary() |
| G3 | Escalation 递归无深度保护 | FIXED — MAX_ESCALATION_DEPTH=3 |
| G4 | `run_turn` 输出格式 | FIXED |
| G5 | 结局检测未接入 | FIXED — process_turn 检查所有 outcomes |
| G6 | Keeper 无单元测试 | DONE — game_loop_harness.py 覆盖 7 轮完整流程 (parse→judge→enrich→narrate)，每轮输出详细 prompt/response 日志

## 优化待办

| # | 问题 | 说明 |
|---|------|------|
| O1 | Step 4 Escalation 每回合 LLM 调用 | **当前焦点** — 见 `keeper.py:154` TODO 注释。计划重新设计 escalation 触发机制，改无条件 LLM 评估为启发式/惰性触发 |
| O2 | Step 6 Memory 压缩阻塞 LLM 调用 | 见 `keeper.py:176` TODO 注释 |
| O3 | Move 限制条件未强制执行 | 见 `keeper.py:83-90` TODO 注释 |

## 架构已知问题 & 计划

| # | 问题 | 处置 |
|---|------|------|
| A1 | ScenarioWorld 职责边界模糊化（God object 趋势） | **FIXED** — 拆分为 Facade + GameClock；markup 解析迁至 game/side_effects.py；npc_states 移除，NPCManager 唯一真源；EnemyManager/NPCManager/BossManager 正式挂载；Keeper 接管 time_costs/comms_interval/apply_side_effects |
| A2 | Author ModulePatch 注入无校验 | 与 O1 一起在 escalation 重设计中解决 |
| A3 | 离线管线 requirement 语义一致性依赖生成质量 | 已有 fallback + 多轮渐进 + 人工审计对冲 |

---

## 修改指南 — 功能 → 代码对应

### 游戏循环主流程

| 功能 | 文件 | 关键位置 |
|------|------|----------|
| 回合入口 + 三 Agent 初始化 | `src/game_loop.py` | `init_game()` / `run_turn()` / `continue_standoff()` |
| Keeper 回合编配主逻辑 | `src/game/agents/keeper.py` | `process_turn():51` |
| Parse — LLM 意图解析 | `src/game/agents/keeper.py` | `_parse()` → `prompts.py:build_keeper_parse_prompt()` |
| Parse — 武器拾取检测 | `src/game/agents/keeper.py` | `process_turn()` 中 `entry_type == "other"` 拾取关键词匹配 |
| Judge — 确定性闸门 | `src/game/judge.py` | `_execute_entity():99` |
| Combat entry 检测 (并行 enrich) | `src/game/agents/keeper.py` | `process_turn()` Step 2.5 → `prompts.py:build_combat_entry_prompt()` |
| Enrich — LLM 叙事润色 | `src/game/agents/keeper.py` | `_enrich()` → `prompts.py:build_keeper_enrich_prompt()` |
| 对峙阶段 | `src/game/agents/keeper.py` | `resolve_standoff()` → `prompts.py:build_standoff_match_prompt()` |
| Curate — 组装 NarratorBrief | `src/game/curator.py` | `assemble():17` |
| Narrator — 最终叙事 | `src/game/agents/narrator.py` | `narrate()` → `prompts.py:build_narrator_prompt()` |
| Memory 记录 + 压缩 | `src/game/agents/keeper.py` | `process_turn()` 末尾 + `src/scenario_core.py:MemoryManager` |

### Author 介入全链路（新）

| 功能 | 文件 | 关键位置 |
|------|------|----------|
| IntentDetector — other 意图检测 | `src/game/intent_detector.py` | `IntentDetector.detect()` |
| AuthorRequest 数据载体 | `src/game/messages.py` | `AuthorRequest:16` / `IntentResult:8` |
| Author — 两级响应 (Patch/Structural/Reject) | `src/game/agents/author.py` | `handle_request():26` |
| Author prompt | `src/prompts.py` | `build_author_prompt()` |
| Keeper — 并行调度 IntentDetector | `src/game/agents/keeper.py` | `process_turn()` 中 `detect_future` 逻辑 |
| Keeper — Author 请求构建 | `src/game/agents/keeper.py` | `_build_scene_context_for_author():342` |
| Patch 集成 | `src/game/agents/keeper.py` | `_integrate_patch():388` |
| StructuralEdit 集成 | `src/game/agents/keeper.py` | `_integrate_supplement():358` |
| StructuralEdit 数据载体 | `src/game/messages.py` | `StructuralEdit:75` |
| Reject 处理 + 玩家提示注入 | `src/game/agents/keeper.py` | `process_turn()` 中 entities=[] 分支 |
| 重复意图抑制 | `src/game/agents/keeper.py` | `_recent_intents` / `_intent_cooldown` |
| WR0 开关 | `src/scenario_core.py` | `ScenarioWorld.wr0_enabled:760` |
| 补充管线 | `src/module_designer/supplement_pipeline.py` | `run_supplement_pipeline()` |

### 数据结构

| 功能 | 文件 | 关键位置 |
|------|------|----------|
| Entity 统一数据类 | `src/scenario_core.py` | `Entity:110` |
| Node / Edge / DirectedGraph | `src/scenario_core.py` | `Node:339` / `Edge:32` / `DirectedGraph:376` |
| ScenarioWorld 运行时状态 | `src/scenario_core.py` | `ScenarioWorld:770`（含 enemy_manager, scene_weapons, weapon_library） |
| runtime_state + dependency_graph | `src/scenario_core.py` | `runtime_state:801` / `dependency_graph:802` |
| hard requirement 解析 (AND/OR) | `src/scenario_core.py` | `parse_hard_requirement():687` |
| dependency_graph 数据结构 | `src/module_designer/dependency_graph.py` | `DependencyEdge:24` / `DependencyGraph:40` |
| @markup 副作用解析 | `src/scenario_core.py` | `parse_markup_all():194` |
| ##GRADED## 分级结果 | `src/scenario_core.py` | `resolve_graded_result():235` |
| ##END_ 结局检测 | `src/scenario_core.py` | `has_ending():259` |
| 消息类型 (dataclass) | `src/game/messages.py` | 全部（含 CombatEntryCheck/CombatInit/StandoffMatch） |
| EnemyInstance + EnemyManager | `src/game/enemy_manager.py` | 纯追踪层，位置/状态/flag 管理 |
| LibraryEnemy + [flag] 解析 | `src/library/enemies.py` | `from_dict()` 从 combat_behavior 前缀提取 |

### 离线管线

| 功能 | 文件 | 关键位置 |
|------|------|----------|
| 管线编排 (13 步) | `src/module_designer/layered_pipeline.py` | `run_pipeline()` |
| 各步 prompt + 解析 | `src/module_designer/layered_parser.py` | 各 `_step_*` 函数 |
| L1/L2/L3 数据模型 | `src/module_designer/l1_player.py` / `l2_keeper.py` / `l3_designer.py` | — |
| Schema 验证 | `src/module_designer/layered_schema.py` | `validate_all()` |
| 管线 CLI 入口 | `run_pipeline.py` | — |

### 测试

| 功能 | 文件 | 覆盖范围 |
|------|------|----------|
| 真实 LLM 集成测试 | `tests/game_loop_harness.py` | 7 轮，parse→judge→enrich→narrate |
| Author 流程单元测试 | `tests/test_author_flow.py` | 8 case，Detector → Author → Keeper 全链路 mock |
| Detector 单元测试 | `tests/test_intent_detector.py` | 3 case，flavor/有意义/空输入 mock |
| Escalation 集成 harness | `tests/test_escalation_harness.py` | 5 case，正常/flavor/Patch/Reject/StructuralEdit，Author 日志 |
| EnemyManager 单元测试 | `tests/test_enemy_manager.py` | 9 case，spawn/filter/group/combat lifecycle/range/context |
| Combat entry 集成测试 | `tests/test_combat_entry.py` | 6 case，spawn→instantiate/gracful_degradation/context/combat_cycle/flag_parsing |

---

```
模组文档 (.docx)
    ↓
Step 1a: 结构化提取 → Step 1b: 精修模组 → chapters
    ↓
Step 2a: Interactions + scene_movements
Step 2b: Events + Auto-triggers (并行)
Step 2c: L1 + L3 (并行)
    ↓
Step 2.5: NPC 行为描述
Step 3a: 去重 + 冲突 + 结局验证
    ↓
组装 L2 → Step 3b: 交叉核对
    ↓
Step 3.5: 依赖图 + Phase 1: 风格预判 (并行)
    ↓
Phase 2: 标准化 (@标记化)
    ↓
最终验证 + 保存 L1/L2/L3 JSON
```

总 LLM 调用: **13 次**

## 特殊标记

| 标记 | 含义 |
|------|------|
| `##GRADED##` | 实际结果在 graded_result 中 |
| `##END_名称:简述##` | 触发游戏结局 |
| `@函数名(参数=值)` | 运行时解析为 side_effect 实例（6种：spawn_enemy/grant_weapon/stat_change/item_gain/consume_item/npc_state_change） |
| `[adjacent_aware]` | Enemy flag：跨场景可感知（如大嘴吞噬者） |
| `[avoidable]` | Enemy flag：存在非战斗绕过途径，触发对峙阶段 |
