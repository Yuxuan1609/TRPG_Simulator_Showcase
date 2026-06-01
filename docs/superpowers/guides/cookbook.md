# COC Simulator Cookbook — 代码导航指南

> 每个模块标注：文件路径 → 核心类/函数 → 功能拆解。供后续 session 快速定位代码。

---

## 1. 游戏循环入口

### `src/game_loop.py` (284 行)

| 函数/类 | 功能 |
|----------|------|
| `init_game(l2_path, l1_path, l3_path, ...)` | 加载 L1/L2/L3 JSON → 构建 DirectedGraph → 加载 EnemyLibrary/WeaponLibrary/BossLibrary → 初始化 BossManager/NPCManager → 创建 ScenarioWorld → 初始化 Keeper/Narrator/Author → 返回 `{keeper, narrator, author}` |
| `run_turn(game, user_input, ...)` | 单回合入口：处理 debug 命令 → 构建 TurnInput → `keeper.process_turn()` → 检测 `combat_init` 调用 `CombatSystem.run_combat()` → `narrator.narrate()` → 返回 `{brief, narrative, full, combat, standoff_prompt}` |
| `continue_standoff(keeper, player_input)` | 对峙阶段处理：`keeper.resolve_standoff()` → 检测结果调用 CombatSystem → 返回 |
| `_handle_spawn_command(...)` | `/spawn enemy <name>` 和 `/spawn weapon <name>` 调试命令处理 |

### `run_game.py` / `notebooks/notebook_simplified.ipynb`
CLI 和 Jupyter 交互入口，调用 `init_game()` + `run_turn()` 循环。

---

## 2. Keeper 回合编配

### `src/game/agents/keeper.py` (~1,020 行)

| 方法 | 功能 |
|------|------|
| `process_turn(turn_input, author)` | **主流程**：`_inject_npc_at()` 注入 NPC entity → Step1 parse(LLM) → NPC 对话路由 → Step2 judge(确定) + 并行 IntentDetect → Step3 [enrich(LLM) ∥ combat_entry(LLM) ∥ TimeAgent(LLM)] → Step4 对峙/CombatInit → Step5 Author → Step6 curate → Step7 memory(后台压缩) → 返回 `{brief, combat_entry, standoff_prompt, combat_init, npc_events}` |
| `_parse(raw)` | LLM parse：玩家输入匹配场景/NPC/全局 entity。NPC entity 按普通类型匹配；`npc_interact` 仅用于无实体匹配的一般性 NPC 对话 |
| `_inject_npc_at()` | 每回合开始：将当前场景 NPC 的 bound entity 注入 node。跳过已完成的 entity |
| `_apply_pending()` | 回合末尾：应用 side effects + 注入跟随 NPC 的 `EVT_NPC_FOLLOW` entity |
| `_find_entity_by_id(eid)` | 跨 graph(场景+events) 查找 entity |
| `_apply_side_effects(side_effects)` | 应用 7 种 @markup side effect dataclass 到世界状态（ItemGain/ConsumeItem/StatChange/SpawnEnemy/GrantWeapon/NPCStateChange/NPCFollow） |
| `resolve_standoff(state, player_input)` | 对峙：语义匹配 LLM → D100 检定 → trait enhancement → 成功转 neutral / 失败进战斗 |
| `_build_world_snapshot()` | 给 IntentDetector 构建世界快照 |
| `_build_scene_context_for_author()` | 给 Author 构建场景上下文 |
| `_integrate_patch(patch)` | Author Patch 实体注入到 graph |
| `_integrate_supplement(structural_edit, author)` | Author StructuralEdit → 补充管线 → 合并 graph + L1 + L3 |
| `_run_time_agent(action_summaries, raw)` | TimeAgent：评估本轮行动耗时（与 enrich 并行，不写 Clock 只返回 time_delta） |

---

## 3. 确定性闸门

### `src/game/judge.py` (324 行)

| 方法 | 功能 |
|------|------|
| `_execute_entity(entity, intent)` | **核心判定**：requirement 检查(hard+soft) → D100 技能检定 → trait enhancement(LLM 特质修正) → ##GRADED## 分级 → **失败惩罚系统**(LLM) → side_effects 解析 → 返回 ActionOutcome |
| `_split_requirement(req)` | 拆分 hard(AND/OR) \|\| soft(自然语言) |
| `_are_requirements_met(entity)` | 硬条件检查：`parse_hard_requirement()` + dependency_graph |
| `_set_completion_flag(entity)` | 标记 entity 完成：更新 runtime_state + dependency_graph 入度 |
| `check_auto_triggers()` | 扫描当前场景 + 全局 events 的满足条件 AT |

---

## 3.5. 失败惩罚系统

### `src/game/judge.py:173-225` + `src/llm.py:344-422`

三层递增机制，在 `_execute_entity()` 内触发（仅当 skill_passed = False）：

| 失败次数 | 触发 | 说明 |
|----------|------|------|
| 第 1 次 | `_escalate_difficulty()` | 实体鉴定难度永久提升一级，写入 `NodeRuntimeState.escalated_difficulty` |
| 第 2 次 | `state.retries++` | 仅递增重试计数 |
| 第 3+ 次 | `evaluate_failure_penalty(LLM)` | 生成创意惩罚叙事 + 可选 @markup 副作用（扣HP/SAN、刷怪、NPC变敌对等），经 `parse_markup_all` 解析后由 `Keeper._apply_side_effects()` 应用 |

**状态追踪**：`NodeRuntimeState`（`src/scenario_core.py:201-207`）每实体一份，含 `retries/escalated_difficulty`，持久化存档。CLI `/flags` 可查询。

**2026-05-22 修复**：失败实体此前被排除在 enrich 的 `judged_entities` 且 `all_outcomes[0].message` 被 unconditionally 覆写，导致惩罚叙事丢失。已修复。

**测试**：`tests/test_failure_penalty.py`（2 case，全 mock）

---

## 4. 战斗系统

### `src/game/combat.py` (371 行)

| 类/函数 | 功能 |
|----------|------|
| `CombatAction` (dataclass) | 单次战斗动作记录：actor/action_type/weapon/skill/roll/tier/target/damage/narrative |
| `CombatState` (dataclass) | 可变战斗状态：round/enemies/player_hp/initiative_order/log |
| `CombatSystem(weapon_lib)` | COC 7th 战斗控制器 |
| `.run_combat(combat_init)` → CombatResult | **主入口**：初始化 CombatState → 逐轮循环 → 返回 CombatResult |
| `._init_combat(combat_init)` | 初始化：解析敌人 hp/先攻 → 构建 CombatState |
| `._process_round(state, player, action_id, target)` | 单轮处理：按先攻序 → 玩家动作 → 敌人动作 → 判定存活 |
| `._resolve_player_action(state, player, action_id, target)` | 玩家 D100 格斗/射击/闪避检定 + 伤害掷骰 + 护甲减免 |
| `._resolve_enemy_action(state, enemy, player)` | 敌人攻击选取 + D100 检定 + 伤害 + 护甲 |
| `._get_tier(roll, skill_value)` | COC 7th 四级检定：≤skill/5=extreme, ≤skill/2=hard, ≤skill=regular |
| `_roll_damage(formula, STR, SIZ)` | 伤害公式解析：1D6+DB、2D6 等 |
| `_apply_armor(damage, armor_str)` | 护甲减免：从 "2点厚皮" 提取数字 |

### `src/game/messages.py` (124 行)

| dataclass | 用途 |
|-----------|------|
| `ActionIntent` | Parse 解析出的玩家意图 |
| `ActionOutcome` | 单个 action 的执行结果(含 skill_tier, skill_detail) |
| `NarratorBrief` | Keeper→Narrator 的策展结果 |
| `AuthorRequest` | IntentDetector→Author：玩家叙事意图 |
| `ModulePatch` | Author→Keeper：entity 补丁 |
| `StructuralEdit` | Author→Keeper：结构扩展 |
| `CombatEntryCheck` | LLM 判定：是否进入战斗 |
| `StandoffMatch` | 对峙语义匹配结果 |
| `CombatInit` | →CombatSystem：战斗初始化数据 |
| `CombatResult` | CombatSystem→：战斗结果 |
| `TurnInput` | 回合入口数据 |

---

## 5. 敌人管理

### `src/game/enemy_manager.py` (170 行)

| 类/方法 | 功能 |
|----------|------|
| `EnemyInstance` (dataclass) | 运行时敌人：instance_id/enemy_ref/scene/quantity/status/flags |
| `EnemyManager(enemy_library)` | 敌人追踪层 |
| `.spawn(enemy_ref, scene, quantity)` → EnemyInstance | 从库实例化敌人，拷贝 flags/combat_behavior |
| `.get_active_in_scene(scene)` → list | 场景中 status != dead 的敌人 |
| `.get_active_in_range(scene, graph)` → list | 当前场景 + adjacent_aware 敌人的相邻场景 |
| `.group_by_ref(scene)` → dict | 同场景按 enemy_ref 分组 |
| `.enter_combat(instance_ids)` | 标记 engaged + 激活 combat 状态 |
| `.exit_combat(result_dict)` | defeated→dead, survivors→hostile, 清除 combat 状态 |
| `.get_combat_context(scene, graph)` → str\|None | 构建 LLM 判定用的敌人信息文本 |
| `.to_dict()` / `.from_dict()` | 序列化/反序列化 |

### `src/game/boss_manager.py` (74 行)

| 类/方法 | 功能 |
|----------|------|
| `BossManager(boss_library, boss_encounters)` | Boss 信息管理（不参与 spawn，由模块预设） |
| `.get_boss(name)` → dict | 获取 Boss stat block + boss_mechanics |
| `.build_combat_init(boss_name, player, scene)` → CombatInit | 从 Boss 数据构造 CombatInit |

---

## 6. NPC 管理

### `src/game/npc_manager.py` (~310 行)

| 类/方法 | 功能 |
|----------|------|
| `NPC` (dataclass) | NPC 实例：name/role/personality/appearance/what_they_can_do/can_follow/scene/attitude/following/bound_interactions/bound_auto_triggers |
| `NPCManager()` | NPC 全量管理 |
| `.init_from_profiles(profiles)` | 从 L2 npc_profiles 批量初始化 |
| `.get_in_scene(scene)` → list | 获取场景中所有 NPC |
| `.talk_to(name, user_input, llm_call)` → str | **对话系统**：LLM 生成 NPC 回复，注入 NPC 档案/态度/记忆上下文 |
| `.process_npc_turn(...)` → dict | **已弃用**——内部 judge/enrich/curate 循环已由主管道接管。保留仅作为独立 API |
| `.set_following(name, bool)` | 同伴跟随切换 |
| `.sync_followers(scene)` | 移动时将跟随 NPC 同步到新场景 |
| `.to_dict()` / `.from_dict()` | 序列化/反序列化 |

---

## 7. 场景世界

### `src/scenario_core.py` (1391 行)

**Side Effects (7 种 @markup)**：

| dataclass | 字段 | 应用路径 |
|-----------|------|----------|
| `SpawnEnemy` | enemy_ref, scene, quantity | → EnemyManager.spawn() |
| `GrantWeapon` | weapon_ref, scene, quantity | → scene_weapons 放置 |
| `StatChange` | stat_name, delta, narrative | → Investigator.modify_stat() + LLM 描述更新 |
| `ItemGain` | item_name, quantity | → ItemManager.add() |
| `ConsumeItem` | item_name, quantity, narrative | → ItemManager.remove() + LLM 模糊匹配保底 |
| `NPCStateChange` | npc_name, new_state | → NPCManager.set_state() |
| `NPCFollow` | npc_name, follow | → NPCManager.set_following() |
| `SceneWeapon` | weapon_ref, scene, quantity | 场景武器追踪 |

**核心类**：

| 类 | 功能 |
|----|------|
| `Entity` | 统一 entity：interaction/auto_trigger/event |
| `Node` | 场景节点：description/edges/interactions/auto_triggers/encounters |
| `Edge` | 连接边：target/method/requirement |
| `DirectedGraph` | 有向图：管理 nodes/events，支持 from_dict/to_dict |
| `ScenarioWorld` | 运行时世界状态 Facade：graph/player/clock/memory/enemy_manager/npcs/bosses/completed_interactions/runtime_state/dependency_graph |
| `MemoryManager` | 分层记忆：raw_history + summary + key_items/visited |

**关键函数**：

| 函数 | 功能 |
|------|------|
| `parse_markup(text)` → dataclass\|None | 解析单个 @函数(参数) 字符串 |
| `parse_markup_all(text)` → list | 解析多个 @markup |
| `apply_side_effects(world, side_effects)` → list[str] | 将 dataclass 实例应用到世界，返回 log 消息 |
| `resolve_graded_result(entity, tier)` → str | ##GRADED## 分级结果解析 |
| `has_ending(text)` → (name, narrative)\|None | ##END_ 结局检测 |
| `parse_hard_requirement(req)` → (met, reason) | AND/OR 结构化的硬条件解析 |

---

## 8. 调查员系统

### `src/investigator/models.py` (391 行)

| 类 | 功能 |
|----|------|
| `Stats` | 8 项核心属性 + LUCK |
| `DerivedStats` | HP/MP/SAN/MOV/DB/BUILD/DODGE |
| `Skill` | 技能定义：name/base_value/value/category |
| `Occupation` | 职业定义 |
| `Weapon` | 武器：name/skill_name/damage/range/malfunction |
| `InventoryItem` | 背包物品：name/description/quantity/category |
| `ItemManager` | 物品管理器：add/remove/has/get/list_all/describe/序列化 |
| `Investigator` | 调查员主类 |
| `Investigator.check_skill(name, difficulty)` | D100 技能检定 |
| `Investigator.modify_stat(stat_name, delta)` | 修改属性(int/dice formula) + 衍生属性重算 |
| `Investigator.add_weapon(w)` / `remove_weapon(name)` | 武器管理 |

### `src/investigator/rules.py` (304 行)
纯函数规则引擎：`roll_stats()` / `calc_derived_stats()` / `calc_db(STR, SIZ)` / `allocate_skill_points()` / `age_modifiers()`

### `src/investigator/serialization.py` (174 行)
`to_json()` / `from_json()` — 调查员 JSON 序列化

---

## 9. 资源库

### `src/library/enemies.py` (145 行)
`LibraryEnemy` / `EnemyLibrary` — 加载 core/enemies.json + extensions，含 `[flag]` 解析（`adjacent_aware`/`avoidable`）

### `src/library/weapons.py` (97 行)
`LibraryWeapon` / `WeaponLibrary` — 加载 core/weapons.json + extensions

### `src/library/bosses.py` (69 行)
`LibraryBoss` / `BossLibrary` — 加载 core/bosses.json，含 `boss_mechanics` 字段

### `src/library/judgment.py` (121 行)
`JudgmentEngine`：T1 确定性 D100 检定 + 伤害掷骰 + SAN 损失 + T2 LLM 增强上下文

### `src/library/injector.py` (99 行)
`ContentInjector`：离线注入（模组构建时）+ 运行时动态注入（`runtime_spawn_enemy`）

---

## 10. Prompt 构建

### `src/prompts.py` (~1,060 行)

| 函数 | 用途 |
|------|------|
| `build_keeper_parse_prompt(world, raw)` | Parse：玩家输入 → entity 匹配。已完成 entity 默认不显示（`SHOW_COMPLETED` 控制） |
| `build_keeper_enrich_prompt(world, entities, input)` | Enrich：检定结果 → 叙事润色 |
| `build_npc_parse_prompt(npc_name, input, bound, bound_at, scene)` | NPC 对话解析：NPC 专属 entity 匹配（按 source_scene 过滤） |
| `build_narrator_prompt(brief, l1, inv_info)` | Narrator：L1 + Brief → 沉浸式叙事 |
| `build_author_prompt(request, l3, ...)` | Author：Patch/StructuralEdit 判定 |
| `build_combat_entry_prompt(player_input, outcomes, enemy_ctx, scene)` | Combat entry：LLM 判定是否进入战斗 |
| `build_standoff_match_prompt(player_input)` | 对峙：语义匹配 → 技能名 |
| `build_stat_narrative_prompt(inv_desc, stat_name, delta, narrative)` | StatChange：LLM 更新调查员描述 |
| `build_consume_item_fuzzy_prompt(target, quantity, held_items)` | ConsumeItem：LLM 模糊匹配背包物品 |
| `build_combat_narrative_prompt(round_log, enemies_desc, player_name, scene)` | 战斗逐轮叙事 |
| `_build_entity_lines(world)` → 8元组 | 构建可触发/不可触发/已完成 entity 列表（场景+NPC+事件三层） |
| `_build_investigator_info(world)` | 调查员状态摘要（供各 prompt 复用） |
| `log_skill_result(detail)` | 技能检定写入日志 `skill_checks.txt` |
| `set_current_round(n)` | 设置当前回合号（供日志命名） |

---

## 11. LLM 封装

### `src/llm.py` (490 行)

| 函数 | 用途 |
|------|------|
| `call_deepseek(prompt, *, json_mode, system, model, thinking, reasoning_effort, fallback_schema)` | **统一 LLM 调用入口**。DeepSeek API 封装。json_mode=True→temperature=0.2；False→0.7。fallback_schema 用于 JSON 解析失败时的保底输出 |
| `evaluate_trait_enhancement(inv_desc, skill_name, skill_detail, current_tier, entity_name, search_context)` | 特质修正评估 |
| `evaluate_failure_penalty(inv_desc, entity_name, skill_name, skill_detail, failure_tier, scene_context, graded_on_failure, retry_count)` | 失败惩罚生成 |

---

## 12. 配置系统

### `src/config.py` (138 行)
集中化配置，不含敏感信息。所有硬编码开关/阈值/魔法数字从此读取。

| 分类 | 配置项 | 默认值 | 说明 |
|------|--------|--------|------|
| 子系统开关 | `WR0_ENABLED` | False | 创作者豁免，开启后 Author 不受世界规则约束 |
| | `COMBAT_LLM_ENHANCEMENT` | False | 战斗 LLM 叙事增强（预留） |
| | `SHOW_NON_TRIGGERABLE` | True | Parse prompt 是否展示未满足条件的实体 |
| | `SHOW_COMPLETED` | False | Parse prompt 是否展示已完成实体 |
| | `JUDGMENT_TIER2_ENABLED` | True | LLM 增强技能判定（Tier 2） |
| 监控阈值 | `LLM_SLOW_THRESHOLD_MS` | 8000 | LLM 慢调用阈值 (ms) |
| | `LLM_TIMEOUT_MS` | 45000 | LLM 超时阈值 (ms) |
| | `LLM_MAX_CONSECUTIVE_FAILURES` | 3 | 触发降级的连续失败次数 |
| | `LLM_DEGRADE_RECOVERY_COUNT` | 5 | 恢复所需连续成功次数 |
| 游戏循环 | `MAX_ESCALATION_DEPTH` | 3 | Author Patch/StructuralEdit 递归上限 |
| | `INTENT_COOLDOWN_WINDOW` | 3 | IntentDetector 去重窗口（回合数） |
| | `COMMS_INTERVAL_MINUTES` | 15 | TimePressure 通信间隔 |
| | `NPC_MEMORY_CAP` | 20 | NPC 对话记忆上限 |
| 降级策略 | `DEGRADE_POLICY` | dict | 每个 Agent 的降级行为（fallback_model/skip/reject_all 等） |
| 管线 | `PIPELINE_MAX_RETRIES` | 3 | LLM 调用最大重试 |
| Prompt 覆盖 | `AGENT_SYSTEM_PROMPTS` | dict | 12 个 Agent 的 system prompt 覆盖（留空 = 用内置默认） |

---

## 13. GameClock

### `src/game/clock.py` (57 行)
纯确定性分钟计时器。不做 LLM 调用，不做叙事逻辑。

| 属性/方法 | 功能 |
|-----------|------|
| `game_time: int` | 累计游戏分钟数 |
| `day` | `game_time // 1440` |
| `hour` | `(game_time % 1440) // 60` |
| `time_of_day` | 5 段：夜间(<5) / 早晨(<8) / 白天(<17) / 黄昏(<20) / 夜间(≥20) |
| `advance_time(minutes)` | 推进时钟 |
| `get_time_flags()` | 返回 `{day:N: True, time:时间段: True}` 供 dependency_graph 检查 |
| `to_dict()` / `from_dict()` | 序列化 |

---

## 14. Curator

### `src/game/curator.py` (54 行)
将 turn outcomes + world state 组装为 NarratorBrief。纯确定性，不调 LLM。

| 方法 | 功能 |
|------|------|
| `assemble(outcomes, ambient_changes, emphasis)` | 组合 ActionOutcome 列表 + 场景快照 + 强调方向 → NarratorBrief |
| `_build_snapshot()` | 从当前场景构建 SceneSnapshot（location/description/exits/perceptible_interactions/visible_npcs） |

---

## 15. TimeAgent

### `src/game/agents/time_agent.py` (75 行)
轻量 LLM 子 Agent。评估本轮行动的时间消耗，不写 Clock（由 Keeper 写）。

| 方法 | 功能 |
|------|------|
| `assess(actions, current_input)` | LLM 评估：综合所有行动 + time_range 建议 → `{time_delta, narrative_hint}` |
| `build_prompt(actions, current_input)` | 构建 prompt：列出每项行动类型、成功/失败、建议耗时范围 |

数据流：Keeper 收集 action_summaries → `TimeAgent.assess()` → `time_delta > 0` 则 `clock.advance_time()` + `clock.time_context` 更新。

---

## 16. Author

### `src/game/agents/author.py` (137 行)
拥有 L3 设计者层。仅面向 Keeper，永远不直接面向玩家。

| 方法 | 功能 |
|------|------|
| `handle_request(request, turn_number)` | 两级响应：**Patch**（填模组缺口，entities 为空 = Reject）或 **StructuralEdit**（触发补充管线） |
| `assess_time_pressure(comms_packet)` | 接收 TimeCommsPacket，判断时间压力是否需要推进 → `{should_press, urgency_update, reason, signal}` |
| `update_l3(l3_updates)` | 合并补充管线产出的 L3 更新 |
| `_build_prompt(request)` | 构造 Author prompt（通过 `build_author_prompt()`） |

WR0 独立可配（`config.py:WR0_ENABLED`）。降级时 `reject_all_structural=True`，仅接受 Patch。

---

## 17. 离线管线

### `src/module_designer/layered_pipeline.py` (~850 行)
`run_pipeline()` — 渐进式解析入口（12 LLM 调用，含 Step 2b events+AT 合并、2.5 NPC 档案+归属合并），含 fallback 策略

### `src/module_designer/layered_parser.py` (~1,420 行)
各步 prompt 构建 + 解析函数。Step 3b 确定性优先 + LLM gap-fill。Phase 2 标准化 7 种 `@函数(参数)` 标记

### `src/module_designer/layered_schema.py` (325 行)
JSON Schema 定义 + `validate_all()` 三层验证

### `src/module_designer/supplement_pipeline.py` (280 行)
`run_supplement_pipeline()` — Author StructuralEdit 触发的轻量补充管线

### `src/module_designer/dependency_graph.py` (140 行)
依赖有向图：构建 + 循环检测 + cut edge

### `src/module_designer/l1_player.py` / `l2_keeper.py` / `l3_designer.py`
L1/L2/L3 数据模型定义

---

## 18. 前端 v2 (FastAPI + HTMX + Precompiled Tailwind)

**设计思路**：Server-rendered SPA（Single Page Application）风格，每页是一个完整的 Jinja2 模板。交互通过 HTMX 声明式 AJAX 实现（无 React/Vue），页面间导航用 `<a href>` 全页加载。游戏回合用 `fetch()` + JSON 响应驱动，不依赖 HTMX 的回合流程。WebSocket 仅用于流水线步骤推送，不承载游戏数据。

### 18.1 项目结构

```
frontend/
├── server.py                    # FastAPI 入口，挂载 6 个 router + StaticFiles + Jinja2
├── static/
│   ├── css/tailwind-built.css   # 预编译静态 Tailwind（94 行手攒 utility class，无 CDN）
│   ├── js/
│   │   └── assets.js            # 素材背景轮播系统（自动检测 context → 加载 → 轮播）
│   ├── assets/                  # 素材背景资源（按页面上下文分文件夹）
│   │   ├── module-gen/          # 模组生成/启动页背景
│   │   ├── game/                # 游戏页背景
│   │   └── character/           # 角色创建页背景
│   └── uploads/avatars/         # 车卡头像上传目录
├── templates/
│   ├── base.html                # 根布局：CSS + HTMX + 背景层(#asset-bg-container) + 遮罩层 + 全局 JS + #file-modal
│   ├── launcher.html            # 启动页：4-tab 导航 + 底部快捷链接（asset_context=launcher）
│   ├── game.html                # 游戏主界面：双面板 + 场景信息卡（左上角）+ 回合卡片堆叠
│   ├── character.html           # 3 步车卡向导 + 全局 JS helper（asset_context=character）
│   ├── editor.html              # JSON 编辑器 3 栏（asset_context=editor）
│   └── partials/
│       ├── launcher-module-gen.html    # 模组生成表单 + 流水线步骤 + 库配置
│       ├── launcher-step0.html         # 小说→模组 Step 0 表单
│       ├── launcher-game-start.html   # 开始游戏表单
│       ├── launcher-config.html       # 全局设置
│       ├── char-step1.html / step2 / step3  # 车卡 3 步向导
│       ├── file-listing.html          # 文件浏览器列表
│       └── help-*.html               # 帮助文本
└── routers/
    ├── launcher.py   # /           启动页 + tab + /api/pipeline/* + /api/step0/* + /api/config/*
    ├── game.py       # /game       游戏循环 + WebSocket + 角色卡 + 场景/NPC
    ├── character.py  # /character  车卡 + LLM 描述 + .zip 导出
    ├── editor.py     # /editor     JSON 编辑（load/save/validate）
    ├── files.py      # /api/files  文件浏览
    └── assets.py     # /api/assets 素材列表/随机抽取（背景轮播后端）
```

### 18.2 设计理念

| 原则 | 说明 |
|------|------|
| HTMX 声明式 | 所有数据加载/表单提交用 `hx-get`/`hx-post`/`hx-target`/`hx-swap` 属性声明，无手写 AJAX |
| 返回 HTML 片段 | 后端端点返回 Jinja2 渲染的 HTML partial，HTMX 直接 swap 到目标 DOM |
| 游戏回合例外 | `/api/game/turn` 返回 JSON（非 HTML），前端 `handleTurnResponse()` 解析 `player_snapshot` 后构造 DOM |
| 全局共享组件放 base.html | 文件浏览模态框 `#file-modal`、`openFileBrowser()`/`closeFileModal()`/`pickFile()` 在 base.html 中定义 |
| 预编译静态 CSS | 手攒 `tailwind-built.css`（94 行），包含全部使用的 utility class + 自定义颜色 token + 动画 |
| 双面板游戏布局 | 左 flex-1 叙事区 + 右 w-72 角色面板，收起态显示头像+HP/SAN 条，点击展开完整卡 |
| PlayerFacingSnapshot 驱动 UI | 游戏回合 JSON 响应包含 `player_snapshot` 字段，前端从中取场景名/时间/出口/NPC/技能/战斗信息渲染 HUD

### 18.3 各页面详细说明

#### server.py (`frontend/server.py`)
- FastAPI app，注册 6 个 router（顺序：files → launcher → character → game → editor → assets）
- 自动从 `config_llm.template.py` 创建配置模板
- `if __name__ == "__main__"`：自动 `webbrowser.open()`，`uvicorn.run("127.0.0.1", 8080)`
- `app.mount("/static", StaticFiles(...))` 提供静态 CSS/JS/素材

#### base.html (`frontend/templates/base.html`)
- 引入 `<link rel="stylesheet" href="/static/css/tailwind-built.css">`
- 引入 `<script src="https://unpkg.com/htmx.org@2.0.4">`
- 引入 `<script src="/static/js/assets.js">`（素材背景轮播系统，所有页面共享）
- `body[data-asset-context]`：每个子模板通过 `{% block asset_context %}` 设置页面上下文（launcher/game/character/editor）
- **背景层体系**（z-index 层级）：
  - `#asset-bg-container` (z=0)：固定全屏，由 `assets.js` 注入图片/视频元素
  - `#content-overlay` (z=1)：固定全屏，半透明遮罩 `rgba(13,13,13,0.72)`，保证文字可读性
  - `#main-content` (z=2)：实际页面内容包裹层
- 内联 CSS：`narrative-flash` 动画、`line-clamp-*`、`.scene-card` / `.scene-card-expanded` / `.char-glass`（毛玻璃效果）
- 全局 JS 函数：`openFileBrowser()` / `closeFileModal()` / `pickFile(path, targetId)`
- `#file-modal` 模态框（z=50），内含 `#file-browser-content` HTMX swap 目标

#### launcher.html — 启动页 4 标签布局
- 左侧 nav (w-56)：**模组生成** / **小说转模组 (Step 0)** / **开始游戏** / **其他工具** 四个 nav-link
- 底部快捷链接：创建调查员 / JSON 编辑器
- 右侧 `#tab-content`：页面加载时自动 `hx-get="/launcher/tabs/module-gen"` 加载首个 tab
- Tab 切换逻辑：`onclick` 内联 JS 更新所有 nav-link active 样式 + `hx-get` 加载对应 partial

#### launcher-module-gen.html — 模组生成标签（Step 1+ 管线）
- 表单 `hx-post="/api/pipeline/start"` `hx-trigger="submit"`
- 字段：source(docx/txt) + module_name + output_dir，均含文件浏览器按钮
- 标准库配置（3 列 grid）：weapon_path / enemy_path / boss_path（含文件浏览器按钮）
- 步骤选择器：完整生成 / 续跑 Step 2a / 续跑 Step 3a / 仅交叉核对(Step 3b)，选择时 `hx-post="/api/pipeline/validate"` 校验中间文件
- `/api/pipeline/start` 后台 `subprocess.run(run_pipeline.py)`，线程异步执行，立即返回"已启动"状态

#### launcher-step0.html — 小说转模组（Step 0 独立步骤）
- 独立于管线，将纯小说/叙事文本转为 9 章节结构化模组文档
- 表单 `hx-post="/api/step0/start"`：输入 txt 源文件路径 + 模组名称
- 输出固定路径：`data/modules/{模组名}/module_step0.txt`
- `/api/step0/start` 后台 `subprocess.run(run_step0.py)`，线程异步执行
- 底部说明：转换完成后如何在"模组生成" tab 中将 txt 传入 Step 1+ 管线

#### launcher-game-start.html — 开始游戏标签
- 表单 `id="init-form"`（无 onsubmit，用 button onclick）
- 3 个模组文件输入（L2/L1/L3）+ 角色卡路径，均含文件浏览器按钮
- **"+ 新建"** 链接跳转到 `/character` 车卡页面
- "开始游戏" 按钮调用内联 `startGame()` 函数：POST `/api/game/init` → 成功后 `window.location.href = '/game'`
- **JS 作用域注意**：`startGame()` 定义在此文件末尾的 `<script>` 中，因为 launcher 页面没有 game.html 的 JS 上下文

#### launcher-config.html — 其他工具 & 设置标签
- JSON 编辑器链接
- 全局 LLM 配置表单：model / flash_model / llm_timeout_ms / reasoning_effort
- Checkbox：thinking / combat_llm_enhancement / debug_mode
- `hx-post="/api/config/save"` 保存到 `config.json`

#### game.html — 游戏主界面（双面板 + 场景信息卡）

**设置屏幕** (`#game-setup`，初始可见):
- 左侧导航 + 快速开始表单（与 launcher 的 game-start 独立）
- 3 个模组文件输入 + 角色卡路径
- 页面加载时自动检测 `/api/game/state`：如果游戏已初始化，直接跳到游戏屏幕

**游戏屏幕** (`#game-screen`，初始隐藏，双面板 + 场景卡):

**场景信息卡** (`#scene-card`，绝对定位左上角):
- 收起态：小横条，显示场景名 (`#scene-card-name`) + 时间 (`#scene-card-time`) + 展开图标
- 展开态：面板，展示场景描述、完整时间、出口列表（标签式）、在场 NPC（带点状标记 + 神态）
- `updateSceneCard(snap)`：从 `player_snapshot` 更新所有字段

左面板（flex-1，`pt-12` 为场景卡留出空间）:
- 顶栏：步骤指示器 + 帮助按钮（场景名已移至场景卡）
- 叙事区 (`#narrative-area`)：`#turn-output` 为每回合输出容器，每条用 `.turn-card` 包裹
  - `.turn-combat`：战斗结果卡片（带图标 + 胜负标签 + 叙事）
  - `.turn-skills`：技能检定标签组（inline-flex 小标签，颜色区分 OK/FAIL + tier）
  - `.turn-brief`：Brief 灰色小字卡片
  - `.turn-narrative`：Narrative parchment 色卡片（aged-gold 左边框 + narrative-flash 动画）
  - `.turn-ending`：结局通知卡片
- 底部输入栏：`#user-input` + 行动按钮（带图标）+ "▲ 展开"
- 展开面板 (`#chat-panel`)：会话记录标题 + `#user-input-expanded` + 行动按钮 + "▼ 收起"

右面板 (w-72, `#char-panel`):
- 收起态：圆形大头像 (`w-12 h-12 rounded-full`) + 名字 + 职业 + HP/SAN 进度条（带标签和动画过渡）
- 展开态：`#char-panel-expanded` 通过 HTMX 加载 `/api/game/character-card`，返回分层结构：
  - 头部：头像 + 名字 + 年龄/性别/职业
  - 属性区：3x3 网格卡片（STR/CON/SIZ/DEX/APP/INT/POW/EDU/LUCK）
  - 状态区：HP/SAN 进度条 + MP/MOV/DB/BUILD/DODGE 一行
  - 技能区：按分类折叠（details/summary），分类包括 战斗/操作/感知/知识/社交，按数值降序排列
  - 武器区：列表
  - 物品区：文本描述

**关键 JS 函数**（定义在 game.html 的 `<script>` 中）:
| 函数 | 功能 |
|------|------|
| `initGame(e)` | 设置屏幕表单提交 → POST `/api/game/init` → 解析 JSON → `updateCharHUD()` → 切换到游戏屏幕 → `connectWS()` |
| `sendTurn()` | 发送回合 → POST `/api/game/turn` → JSON → `handleTurnResponse()`，HTML → 直接插入 `#turn-output` |
| `handleTurnResponse(userText, data)` | 解析 JSON → `updateSceneCard(snap)` 更新场景卡 → 构建 `.turn-card`（combat/skills/brief/narrative）→ 追加到 `#turn-output` → 检测 game_over |
| `toggleSceneCard()` | 展开/收起场景信息卡，切换 CSS class |
| `updateSceneCard(snap)` | 从 `player_snapshot` 更新场景名/时间/描述/出口/NPC |
| `toggleCharCard()` | 展开/收起角色面板 → HTMX 加载角色卡 |
| `updateCharHUD(data)` | 更新角色面板收起态（头像/名字/职业/HP/SAN 条） |
| `togglePanel(show)` | 展开/收起聊天面板 |
| `addToHistory(userMsg, responseHtml)` | 追加到 `chatMessages[]`，限制 200 条 |
| `connectWS()` | WebSocket 进度流，指数退避重连 |

#### 部分 (partials)
| 文件 | 加载方式 | 功能 |
|------|----------|------|
| `file-listing.html` | `/api/files` 返回，HTMX swap 到 `.file-listing-container` | 文件浏览器：面包屑（含 HTMX 导航）+ 目录列表 + 文件列表（按扩展名过滤 .json/.docx/.txt/.pdf/.md），`onclick="pickFile(path, targetId)"` |
| `help-game.html` | — | 游戏帮助文本参考（当前已弃用，帮助命令改由 `_handle_slash_command()` 内联生成 HTML） |
| `help-editor.html` | — | JSON 编辑器参考文档（@markup 标记说明） |
| `help-character.html` | — | COC 7th 属性/技能参考文档 |
| `char-step1/2/3.html` | `/character/step/{n}` | 车卡 3 步向导 partial |
| `launcher-module-gen.html` | `/launcher/tabs/module-gen` | 模组生成表单 |
| `launcher-step0.html` | `/launcher/tabs/step0` | 小说→模组 Step 0 表单 |
| `launcher-game-start.html` | `/launcher/tabs/game-start` | 快速开始游戏表单 |
| `launcher-config.html` | `/launcher/tabs/config` | 全局设置表单 |

### 18.4 后端 API 端点详情

#### launcher.py 端点
| 路由 | 方法 | 功能 | 返回 |
|------|------|------|------|
| `/` | GET | 启动页 | launcher.html |
| `/launcher/tabs/{tab}` | GET | 动态加载 tab partial（module-gen / step0 / game-start / config） | launcher-module-gen / launcher-step0 / launcher-game-start / launcher-config |
| `/api/config/save` | POST | 保存 config.json（model/thinking/reasoning_effort/debug） | 纯文本 "配置已保存 ✓" |
| `/api/config/load` | GET | 读取 config.json | JSON |
| `/api/pipeline/start` | POST | 启动模组生成管线（子进程 `run_pipeline.py`） | HTML 状态消息 |
| `/api/pipeline/validate` | POST | 校验续跑中间文件存在性 + JSON 合法性 | HTML 校验结果 |
| `/api/step0/start` | POST | 启动 Step 0 小说→模组转换（子进程 `run_step0.py`） | HTML 状态消息 |

#### game.py 端点
| 路由 | 方法 | 功能 | 返回 |
|------|------|------|------|
| `/game` | GET | 游戏页面 | game.html |
| `/api/game/init` | POST | 初始化游戏引擎 + 自动跑 [游戏开始] 首回合 | JSON `{success, location, hp, san, name, initial_brief, initial_narrative}` |
| `/api/game/turn` | POST | 回合入口。`/` 开头走 `_handle_slash_command()` 短路，否则走 `run_turn()` | JSON `{brief, narrative, narrative_html, combat, skill_results, game_over, ending, timestamp, player_snapshot}` |
| `/api/game/player-status` | GET | 玩家 HP/SAN。`?format=json` 返回 JSON 含 `hp_max` + `avatar_url` | HTML 或 JSON |
| `/api/game/scene` | GET | 当前场景信息 | HTML |
| `/api/game/npcs` | GET | 当前场景可见 NPC | HTML |
| `/api/game/state` | GET | 完整游戏状态快照 | JSON `{location, turn, hp, san, name}` |
| `/api/game/character-card` | GET | 完整角色卡 HTML（属性/技能/武器/物品/头像） | HTML |
| `/api/game/command` | POST | 旧命令端点（仍可用，斜杠命令现在走 process_turn 短路） | HTML |
| `/api/game/progress` | WebSocket | 流水线步骤推送 `{step, status}` | JSON stream |

**斜杠命令列表**（`_handle_slash_command()` 处理）:
`/help` `/scene` `/char` `/flags` `/events` `/save <slot>` `/load <slot>` `/quit` `/exit` `/reset`

#### character.py 端点
| 路由 | 方法 | 功能 |
|------|------|------|
| `/character` | GET | 车卡向导页 |
| `/character/step/{n}` | GET | 步骤 1/2/3 partial |
| `/character/roll` | POST | 掷骰生成属性 |
| `/character/skills-list` | GET | 按职业加载技能列表 |
| `/character/generate-description` | POST | LLM 生成外貌/个人描述 |
| `/character/export` | POST | 导出 Investigator JSON（含 `avatar_url`） |

#### editor.py 端点
| 路由 | 方法 | 功能 |
|------|------|------|
| `/editor` | GET | JSON 编辑器页 |
| `/editor/load?path=` | GET | 加载 JSON 为可折叠树 |
| `/editor/save` | POST | 保存 JSON 到文件 |
| `/editor/validate` | POST | 校验 JSON 结构 |

#### files.py 端点
| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/files?dir=&target_input=` | GET | 文件浏览器：面包屑 + 目录 + 文件列表 |

#### assets.py 端点（素材背景系统）
| 路由 | 方法 | 功能 | 返回 |
|------|------|------|------|
| `/api/assets/list?context=` | GET | 列出指定页面上下文的素材（图片+视频） | JSON `{images:[], videos:[], context, folder}` |
| `/api/assets/random?context=` | GET | 随机返回一个素材（可过滤 type=image/video） | JSON `{url, type, name}` |

**Context 映射**：`launcher` → `module-gen` / `game` → `game` / `character` → `character` / `editor` → `game`

**前端轮播**：`assets.js` 自动检测 `body[data-asset-context]` → 加载列表 → 图片/视频淡入淡出轮播（默认 30s，可配置 `AssetCarousel.setInterval(ms)`）

### 18.5 数据流关键路径

**从启动到游戏**：
```
Launcher(/) → 点击"模组生成"tab → hx-get /launcher/tabs/module-gen
           → （可选）点击"小说转模组(Step 0)"tab → hx-get /launcher/tabs/step0
           → 点击"开始游戏"tab → hx-get /launcher/tabs/game-start
           → 填写表单 → 点击"开始游戏" → startGame()
           → POST /api/game/init → 初始化 game_instance + 自动跑首回合
           → 成功 → window.location.href = '/game'
Game(/game) → 页面加载 → IIFE fetch /api/game/state
           → 已初始化 → 跳过设置屏幕 → updateCharHUD() → connectWS()
```

**单回合流程**：
```
用户输入 → sendTurn() → POST /api/game/turn (FormData)
  ├─ 以 "/" 开头 → _handle_slash_command() → 返回 JSON {narrative_html: cmd_result}
  └─ 否则 → run_turn() → 返回 JSON {brief, narrative, combat, skill_results, player_snapshot, ...}
       → handleTurnResponse() → updateSceneCard(snap) 更新场景卡
                              → 构建 .turn-card（combat/skills/brief/narrative）
                              → 追加到 #turn-output（可滚动历史）
       → fetch /api/game/player-status?format=json → updateCharHUD()
```

**WebSocket 进度流**：
```
connectWS() → ws://host/api/game/progress
  ← {step: "parse", status: "running"}
  ← {step: "parse", status: "done"}
  ...
  ← {step: "complete"}
→ 更新 #step-indicator
→ 断连时指数退避重连，wsRetry 在 onopen 清零
```

### 18.6 常见问题排查

| 问题 | 检查点 |
|------|--------|
| 按钮无反应 | (a) 函数是否定义在当前页面的 `<script>` 中（HTMX partial 的 JS 作用域） (b) hx-post 目标元素是否存在 |
| 文件浏览器不弹出 | `#file-modal` 是否在 base.html 中（`{% block body %}` 之后） |
| 样式缺失 | `tailwind-built.css` 是否包含该类（浏览器 DevTools → Elements → Styles → 搜索 class） |
| 斜杠命令不生效 | `process_turn` 的 `/` 开头拦截是否在 `get_game()` 之前执行 |
| 页面加载显示设置屏幕 | `/api/game/state` 是否返回已初始化的游戏（检查 `_game_instance` 全局变量） |
| 素材背景不显示 | (a) `frontend/static/assets/<context>/` 是否有文件 (b) 浏览器 Network 面板 `/api/assets/list` 是否 200 (c) `body[data-asset-context]` 是否正确设置 |
| 背景素材遮挡内容 | 检查 `#content-overlay` 是否存在且 `z-index` 在 `#asset-bg-container` 之上 |
| 场景卡不更新 | 检查 `handleTurnResponse()` 是否调用了 `updateSceneCard(snap)`，以及 `player_snapshot` 是否包含 `scene_name` |
| 角色卡展开太密 | 正常现象——展开态采用分层折叠设计，技能区使用 `<details>` 分类折叠，点击分类标题展开 |

### 18.7 素材系统详解

**目录结构**：
```
素材/                          # 原始素材库（项目根目录）
├── images_src/               # 39 张图片（自动归类）
├── videos_src/               # 14 个视频（自动归类）
├── module_gen/               # 模组生成用素材子集
├── game_run/                 # 游戏运行用素材子集
└── character_create/         # 角色创建用素材子集

frontend/static/assets/       # 前端实际服务的素材
├── module-gen/               # 5 个文件（launcher 共用）
├── game/                     # 10 个文件（7 图 + 3 视频）
└── character/                # 5 个文件
```

**后端**：`assets.py`
- `CONTEXT_MAP` 将页面上下文映射到物理文件夹
- `/api/assets/list?context=`：返回 `{images:[{url,type,name}], videos:[...]}`
- `/api/assets/random?context=&type_filter=`：随机抽取单个素材

**前端**：`assets.js`（`frontend/static/js/assets.js`）
- `AssetCarousel.init()`：检测 `body[data-asset-context]` → fetch 列表 → 创建 `#asset-bg-container` → 轮播
- `AssetCarousel.setInterval(ms)`：动态调整轮播间隔（默认 30000ms）
- `AssetCarousel.destroy()`：清理轮播
- 配置项：`CONFIG.interval` / `CONFIG.fadeDuration` / `CONFIG.videoMuted` / `CONFIG.videoLoop`
- 图片用 CSS `background-image` 展示，视频用 `<video>` 元素展示
- 切换时新元素 opacity 0→1，旧元素延迟 `fadeDuration` 后移除

**添加新素材**：将文件放入 `frontend/static/assets/<context>/` 即可，无需重启服务（StaticFiles 实时读取）

---

## 19. 测试

| 文件 | 覆盖 | 类型 |
|------|------|------|
| `tests/test_enemy_manager.py` (9 case) | spawn/filter/group/combat/range/context | 单元 |
| `tests/test_combat_entry.py` (6 case) | SpawnEnemy→EnemyManager→combat lifecycle | 集成 |
| `tests/test_combat.py` (10 case) | damage/armor/tier/state/CombatSystem | 单元 |
| `tests/test_combat_harness.py` | CombatSystem 完整战斗流程 | 集成 |
| `tests/test_boss_manager.py` | BossManager spawn/combat_init | 单元 |
| `tests/test_boss_library.py` | BossLibrary load/get | 单元 |
| `tests/test_npc_manager.py` | NPCManager talk/attitude/serialize | 单元 |
| `tests/test_library.py` (18 case) | Weapon/EnemyLibrary + flag 解析 | 单元 |
| `tests/test_author_flow.py` (8 case) | Detector→Author→Keeper mock | 单元 |
| `tests/test_intent_detector.py` (3 case) | flavor/有意义/空输入 | 单元 |
| `tests/test_escalation_harness.py` (5 case) | 正常/flavor/Patch/Reject/StructuralEdit | 集成(真实LLM) |
| `tests/test_failure_penalty.py` (2 case) | Judge惩罚生成→Keeper enrich保留→Narrator接收 | 单元(全mock) |
| `tests/game_loop_harness.py` (7 轮) | parse→judge→enrich→narrate | 集成(真实LLM) |
| `tests/test_harness_stability.py` (2 case) | 正常探索 + 混合压力，3轮/每轮3turn | 集成(真实LLM) |
| `tests/test_harness_parallel.py` (16 case) | search/检定/依赖/AT/NPC/武器/move/对峙/战斗/道具/属性/结局 | 集成(真实LLM+mock) |
| 其他 | test_judge/dependency_graph/directed_graph/entity/entity_resolvers/curator/integration/module_designer | 单元+集成 |

---

## 20. 关键数据流速查

```
离线管线: .docx → layered_pipeline(12 LLM calls) → l1/l2/l3.json

运行时加载: l2.json → DirectedGraph → ScenarioWorld(npc_manager, enemy_manager, ...)
            l1.json → Narrator
            l3.json → Author
            enemies.json → EnemyLibrary → EnemyManager
            weapons.json → WeaponLibrary
            bosses.json → BossLibrary → BossManager

单回合: user_input → Keeper.process_turn()
           ├─ _inject_npc_at() → NPC bound entities 注入当前场景
           ├─ parse(LLM) → entity matches
           ├─ [NPC 路由]:
           │   ├─ [NPC_INTERACT]/[NPC_AT] entity → interaction/auto_trigger → 走主管道
           │   └─ npc_interact(无匹配) → talk_to() → 短路返回对话
           ├─ judge(deterministic) → D100 + @markup + [失败≥3次 → LLM 惩罚]
           ├─ [enrich(LLM) ∥ combat_entry(LLM) ∥ TimeAgent(LLM)]
           ├─ [对峙(avoidable): 语义匹配(LLM) → D100 → trait_enhancement]
           ├─ curate → NarratorBrief
           ├─ [IntentDetect → Author → Patch/StructuralEdit (按需)]
           └─ narrator(LLM) → immersive narrative
           ╎ 独立管线: skill_detail → CLI + 日志
           ╎          TimeAgent → clock.advance_time()

战斗: CombatInit → CombatSystem.run_combat()
        ├─ _init_combat → CombatState
        ├─ 逐轮: 玩家动作(D100) + 敌人动作(D100) + 伤害(公式+护甲)
        └─ CombatResult → EnemyManager.exit_combat()
```

---

## 21. 环境约定

- **Python path**：所有命令需要 `PYTHONPATH="src"`（Windows 用 `set PYTHONPATH=src`）
- **测试命令**：`cd C:/Users/micha/PyCharmMiscProject && $env:PYTHONPATH="src"; python tests/<file> --case B`
- **LLM 模型**：默认 `deepseek-v4-pro`（重推理），flash 任务用 `deepseek-v4-flash`（轻量）
- **推理强度**：`reasoning_effort`: 重任务 `"high"`，轻任务 `"low"`
- **JSON mode**：结构化判定 `json_mode=True`（temperature=0.2），叙事生成 `json_mode=False`（temperature=0.7）
- **关键配置项** (`src/config.py`)：`SHOW_NON_TRIGGERABLE`（展示不可触发实体）、`SHOW_COMPLETED`（展示已完成实体）、`COMBAT_LLM_ENHANCEMENT`（战斗 LLM 叙事增强）
