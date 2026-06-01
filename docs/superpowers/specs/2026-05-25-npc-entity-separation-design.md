# NPC ↔ Entity 分离设计

日期: 2026-05-25

## 1. 概述

在现有 NPC 机制（`npc_manager.py` + Step 2.5 npc_profiles）基础上，进一步分离 NPC 与 Entity 系统：

- **模组生成阶段**：NPC 相关 entity 从 scene 中剥离，绑定到对应 NPC；NPC 跟随/离开不生成 entity
- **运行时**：NPC 对话走独立 turn（自有 parse → 复用 enrich/curator/narrator）；NPC AT 条件满足时动态注入主 parse
- **独立输出**：`npcs_visible`（始终渲染）+ `npc_events`（固定预料通知）

## 2. 模组生成阶段

### 2.1 Step 2a/2b Prompt 变更

Step 2a（interactions）、Step 2b events、Step 2b AT 的 system prompt 新增：

```
- NPC互动是否生成 entity 的判断标准：entity 必须有可感知的游戏机制后果——
  技能检定、物品给予/消耗、属性变化、NPC状态变更（受伤/死亡等）、
  触发新的事件、场景永久性变化。
  单纯的NPC对话/交谈/打听消息（无机制后果的信息传递）不生成 entity，
  由运行时 NPC 对话系统处理。
- NPC 跟随/离开/加入队伍不生成 entity（由运行时 NPC 跟随机制处理，
  条件由 npc_profile 的 can_follow + follow_requirements 控制）。
  entity 中不出现 NPC 跟随/离开玩家的描述。
```

### 2.2 确定性后处理：Entity 剥离与绑定

`_assemble_l2()` 之前新增 `_bind_npc_entities()` 步骤（纯确定性，不调 LLM）：

```
输入：interactions[], auto_triggers[], npc_profiles{}
处理：
  遍历 interactions + auto_triggers
  对每个 entity，检查 name/trigger/result 是否包含 npc_profiles 中任意 NPC 名称
  命中 → 从 scene entity list 移除 → 归入 npc_profiles[name].bound_interactions
       或 .bound_auto_triggers
  同时：筛掉 NPCEventType 为 follow_start/follow_stop 的 entity（不绑定，直接丢弃）
输出：interactions[], auto_triggers[], npc_profiles{}（含 bound_* 字段）
```

NPC 名称匹配规则：精确名称匹配（不区分全角/半角空格），不做模糊匹配。

**关键约束**：entity 从 scene 剥离绑定到 NPC 时，`id` 字段保持不变。依赖图中的 edge 通过 entity ID 引用，改变 ID 会导致依赖链失效。

绑定 entity 需保留来源信息：
```python
bound_interactions: list[dict]   # 每个 entity 保留原始字段 + "source_scene": "场景名"
bound_auto_triggers: list[dict]  # 每个 entity 保留原始字段 + "source_scene": "场景名"
```
`source_scene` 记录 entity 原本所在的场景（interaction/AT）或标记为 `"global"`（event）。运行时 NPC turn 仅激活当前场景匹配的 bound entity。

### 2.3 NPCProfile 新增字段

```python
@dataclass
class NPC:
    # 档案字段（Step 2.5 产生）
    name: str
    role: str
    personality_notes: str
    appearance: str
    what_they_can_do: str
    interaction_triggers: list[str]
    can_follow: bool = False          # 模组预设：NPC 是否愿意/能够跟随调查员
    follow_requirements: str = ""     # 跟随前置条件（entity ID链，如 "I3 AND I5"），
                                       # 由管线后处理从 entity 依赖推断填充

    # 绑定 entities（管线后处理确定性填充，非 Step 2.5 产生）
    bound_interactions: list[dict]   # 从 scene 剥离的 interaction
    bound_auto_triggers: list[dict]  # 从 scene 剥离的 auto_trigger
```

`can_follow` 由 Step 2.5 从模组内容推断（NPC 的性格/处境是否支持跟随调查员）。
`follow_requirements` 由管线后处理 `_bind_npc_entities()` 从相关 entity 的依赖关系自动推断填充。
`bound_*` 字段不在 Step 2.5 prompt 中生成，由管线 `_bind_npc_entities()` 确定性填充。

### 2.4 Step 2.5 变更

Step 2.5 新增生成 `can_follow` 字段（bool），从模组内容推断 NPC 是否愿意/能够跟随调查员。除此之外继续生成档案字段（name/role/personality_notes 等），不新增其他字段。`follow_requirements` 由管线后处理填充（见 2.2）。

## 3. 运行时

### 3.1 数据流总览

```
玩家输入
  │
  ├─ NPC 名字匹配? ──是──→ flash LLM 对话意图判定
  │                          │
  │                     是对话? ──否──→ 回退正常 parse 管线
  │                      │
  │                  ┌───┘
  │                  ▼
  │         NPCManager.process_npc_turn(npc, user_input)
  │           ├─ 1. talk_to() —— LLM 扮演 NPC 生成对话文本
  │           │     状态门：dead/left → 确定性拒绝
  │           │     其他状态 → LLM 自行解读
  │           ├─ 2. NPC Parse —— 匹配玩家输入 vs npc.bound_interactions
  │           │     返回匹配 entity 列表（可空）
  │           ├─ 3. Judge —— 对匹配 entity 跑技能检定（复用 JudgeEngine）
  │           ├─ 4. enrich(LLM, 复用 build_keeper_enrich_prompt)
  │           ├─ 5. TimeAgent(LLM, 复用)
  │           └─ 6. curator → narrator（复用主循环）
  │
  └─ 非对话 → parse → judge → enrich ∥ combat_entry ∥ TimeAgent
                → [对峙] → curate → narrator
```

### 3.2 NPC 对话意图判定

Keeper 检测 `npc.name in raw` → flash LLM 判定：

```
你是回合解析助手。判断玩家输入是否真的是在和 NPC 对话。
输入：玩家输入 + NPC 名称
排除：引号引用（"写着'老妇人'"）、非对话场景
输出：{"is_talking": true/false, "npc_name": "名称"}
```

`is_talking=false` → 回退正常 parse 管线（不短路）。

### 3.3 NPC Turn — talk_to()

状态门（确定性）：

| state | 行为 |
|-------|------|
| `dead` | 返回 `"(XXX 已无法交谈)"` |
| `left` | 返回 `"(XXX 不在此处)"` |
| 其他 | LLM 扮演 NPC 生成回复 |

System prompt 注入：
- 角色/性格/外貌/`能力与所知信息`(what_they_can_do)
- `互动触发条件`(interaction_triggers) — **新字段**
- 态度/状态/最近 5 条对话记忆
- 信息交付指令：`若调查员询问或触及互动触发条件中的信息，应如实告知所知内容，不刻意隐瞒`

### 3.4 NPC Parse

确定性 + LLM 混合（类似主 parse 但 scope 限制在 `npc.bound_interactions`）：

```
输入：玩家输入 + npc.bound_interactions[] + npc.bound_auto_triggers[]
输出：匹配的 entity IDs（可空）
```

匹配规则：LLM 判定玩家输入是否触发了任意 bound entity 的 trigger。

### 3.5 NPC AT 动态注入

每轮 Keeper.process_turn() 中，遍历所有 NPC 的 `bound_auto_triggers`：
- 确定性检查 requirement（dep graph / runtime_state / world state）
- 条件满足 → 注入到主 parse prompt 的 `【可触发】` entity 列表
- 不依赖玩家主动找 NPC 对话

### 3.6 NPC 跟随

两种触发源，均走同一条件检查：

| 触发源 | 场景 | 示例 |
|--------|------|------|
| `@npc_follow` markup | entity side effect 触发 | 救下 NPC → `@npc_follow(npc_name="老妇人", follow=true)` |
| 玩家主动请求 | NPC turn 中 NPC parse 检测到跟随意图 | "跟我来" / "跟我走" |

**条件检查**（`NPCManager._check_follow_conditions(npc, world) -> bool`）：

1. `npc.can_follow == True` — NPC 本身愿意/能够跟随
2. `npc.follow_requirements` 满足 — 通过 dependency graph 检查 entity ID 链（如 `I3 AND I5` 均已完成）
3. `npc.state not in ("dead", "left")` — NPC 必须存活且在场景内

**执行**：

- 条件通过 → `NPCManager.set_following(name, True)` → `npc_events` 追加 `"{name} 开始跟随你"`
- 条件不通过 → NPC 对话中说明原因（`talk_to` 处理拒绝理由）

**停止跟随**：

- `@npc_follow(npc_name=X, follow=false)` → `NPCManager.set_following(X, False)` → `npc_events` 追加 `"{name} 停止了跟随"`
- 场景切换 → `NPCManager.sync_followers(new_scene)` 自动移动跟随 NPC

NPC follow/leave 的 entity 在管线后处理中被筛掉（见 2.2），不会出现在任何 scene 的 entity list 中。

### 3.7 独立输出通路

`run_turn()` 返回新增字段：

```python
{
    "npcs_visible": {
        "in_scene": ["老妇人"],      # 当前场景内可交互 NPC
        "following": ["张三"]        # 跟随调查员的 NPC
    },
    "npc_events": ["老妇人开始跟随你"],  # 固定预料（无 LLM）
    ...
}
```

前端始终渲染 `npcs_visible`，格式：`NPC:XXX 可交互`。`npc_events` 为独立系统通知。

## 4. 冲突处理

| # | 冲突 | 处理 |
|---|------|------|
| 1 | NPC 死/离开后对话 | 状态门 dead/left 硬拒绝，其他状态 LLM 自行解读 |
| 2 | NPC 名误匹配 | flash LLM 对话意图判定，非对话回退 parse |
| 3 | Entity requirement 引用 NPC 状态 | 软性条件（`\|\|` 后自然语言）+ LLM 判断，暂不做确定性扩展 |
| 4 | Requirement 确定性 NPC 语法 | TODO（readme） |
| 5 | NPC 对话 + 实体动作混合 | 进 NPC turn 走 NPC parse 匹配 bound entities，复用 judge |
| 6 | NPC AT 不被触发 | 条件满足时动态注入主 parse prompt |
| 7 | 跟随/离开在 entity 中出现 | 管线后处理筛掉；运行时纯确定性 |

## 5. TODO（readme 记录，不实现）

- NPC 态度层级复杂影响（hostile/wary/neutral/friendly/trusting → 信息透露量/检定难度/战斗触发）
- 世界状态更新纳入 NPC 关键事件
- 半主动 NPC ambient triggers 系统
- requirement 确定性 NPC 状态检查语法（`NPC:name.attitude=X`）
- 多调查员 NPC 战斗参与
- NPC bound entity 跨场景激活细化：当前 source_scene 精确匹配较粗糙——NPC 移动后原场景 entity 是否仍可选、部分 AT 是否应跨场景生效，需要更细粒度的激活规则

## 6. 实施步骤

1. **管线层**：`_bind_npc_entities()` 确定性后处理 + Step 2a/2b prompt 修改
2. **NPCManager**：`talk_to()` 状态门 + prompt 增强 + `process_npc_turn()` + NPC parse
3. **Keeper**：NPC 对话意图判定（flash LLM）+ NPC turn 集成 + NPC AT 注入
4. **独立输出**：`npcs_visible` + `npc_events` 字段
5. **跟随清理**：Step 2a/2b prompt 排除 NPC 跟随/离开 entity
6. **readme**：TODO 条目更新
7. **测试**：test_npc_manager.py 扩增（NPC parse / AT 注入 / 意图判定）
