# Dependency Graph + Runtime State / Requirement 解析 / @markup 完备性

日期：2026-05-18
状态：设计阶段
范围：`scenario_core.py`, `game/judge.py`, `game/agents/keeper.py`

## 1. Dependency Graph 统一 World Flags

### 动机

当前系统有两套重叠的依赖/状态追踪机制：
- `world.flags: Dict[str, bool]` — 运行时动态标记（`{eid}_done`, `{eid}_failed`, `{eid}_retries`）
- `dependency_graph` (L2 静态) — 实体间的依赖关系（edges）

两者都在表达"某实体是否可触发"，但数据结构不统一，增加了维护成本和一致性风险。

### 设计

两层结构：**静态 graph 骨架**（来自 L2，不可变）+ **动态 runtime_state**（运行时填充，不改 graph）。

#### dependency_graph（静态，L2 定义）

```python
class DependencyNode:
    entity_id: str      # "I1"
    entity_type: str    # "interaction" | "auto_trigger" | "event"

class DependencyEdge:
    source: str         # 依赖者（"I2" 依赖 I1）
    target: str         # 被依赖者
    condition: str      # "success" | "fail" | "completed" | "Uncompleted"
```

#### runtime_state（动态叠加层）

```python
@dataclass
class NodeRuntimeState:
    completed: bool = False
    result_tier: str = ""          # "" | "fumble" | "failure" | "regular" | "hard" | "extreme"
    retries: int = 0               # 累计失败次数
    escalated_difficulty: str = ""  # 升级后的难度（"hard" | "extreme"）
```

#### 与旧 flag 的映射

| 旧 flag | 新 runtime_state |
|---|---|
| `{eid}_done` (bool) | `state.completed = True` |
| `{eid}_retries` (int) | `state.retries = N` |
| `{eid}_failed` (bool) | `state.result_tier in ("failure", "fumble")` |
| `{eid}_difficulty` (str) | `state.escalated_difficulty` |

旧 `world.flags` 字典移除。

### 依赖解析

```python
def check_entity_requirements(entity_id: str, graph, runtime_state) -> bool:
    """查找所有 source=entity_id 的 edge，AND 语义逐一验证 target 状态。
    OR 语义由 requirement 字段的字符串解析处理（见第 2 节）。"""
    for edge in graph.incoming_edges(entity_id):
        target_state = runtime_state.get(edge.target)
        if not target_state:
            return False
        if edge.condition == "success":
            if target_state.result_tier not in ("regular", "hard", "extreme"):
                return False
        elif edge.condition == "completed":
            if not target_state.completed:
                return False
        elif edge.condition == "fail":
            if target_state.result_tier not in ("failure", "fumble"):
                return False
        elif edge.condition == "Uncompleted":
            if target_state.completed:
                return False
    return True
```

### Judge 写入

- **成功**：`runtime_state[entity.id].completed = True`，`.result_tier = tier`
- **失败**：`runtime_state[entity.id].retries += 1`，`.escalated_difficulty` = 升级后的难度

### Escalation / Author 介入

- 加新 node/edge → 改 graph 骨架（稀有操作，重是合理的）
- 只改状态 → 写 runtime_state（常规操作，轻量）
- graph 始终保持 L2 来源的纯净性，runtime_state 类似"存档"

---

## 2. Requirement 字段解析

### 格式规范（新 L2 为准）

hard requirement 仅涉及 **entity ID + `OR` 逻辑符**。AND 语义由 dependency_graph edges 表达。
考虑一下符合逻辑下AND语义的情况：比如 （A OR B）AND C
```
requirement = hard "||" soft?

hard = group ("OR" group)*
group = 经过 strip 后的 entity ID (I/E/AT + 数字 + 可选小写字母)

soft = 任意自然语言
```

### 解析顺序

```
requirement 原始字符串
  │
  ├─ 1. split("||", 1) → hard, soft
  │
  ├─ 2. hard 部分（确定性）
  │     ├─ 空/只有空白 → pass
  │     ├─ split("OR") / split(" or ") → ["I1", "I9", "(I12a)", ...]
  │     ├─ 每个 group：
  │     │    ├─ strip 多余字符：空格、括号、中文标点
  │     │    ├─ regex 提取 [IEA]+\d+[a-z]?
  │     │    ├─ 匹配到 ID → 查 runtime_state/dependency_graph
  │     │    └─ 无 ID → pass（视为无条件）
  │     └─ OR 语义：任一 group pass → hard 整体 pass
  │
  └─ 3. soft 部分（LLM 辅助）
        └─ 非空时送 LLM flash 模型判断（叙事性条件，如"调查员持有光源"）
```

### Corner cases

| 输入 | 处理 |
|---|---|
| `""` | pass |
| `"I1"` | 直接查 runtime_state[I1].completed |
| `"I16 OR I17"` | split("OR") → ["I16", "I17"]，任一 completed → pass |
| `"(I12a OR I12b)"` | strip 括号后同上 |
| `"\|\|I4检定失败"` | hard=""→pass, soft="I4检定失败"→LLM |
| `"\|\|调查员持有光源"` | hard=""→pass, soft="调查员持有光源"→LLM |
| `"I1 AND I9"` | 不支持混合 AND 在字符串中，AND 走 edge |

### edge 与 requirement 的优先级

- **edge 优先**：如果 graph 存在 source=entity_id 的 edge，直接用 edge 做 AND 依赖判断
- **requirement 兜底**：edge 覆盖不了的（OR 逻辑、软条件）走 requirement 字符串解析
- 两者互补，不是冗余

### LLM fallback（仅 soft 部分）

```python
def evaluate_soft_requirement(expr: str, world_context: dict) -> bool:
    """轻量 LLM 调用，判断叙事性条件是否满足。
    用 deepseek-v4-flash, thinking=disabled, temperature=0.2。
    expr: "调查员持有光源（如手电筒、手机闪光灯）"
    返回: {"met": bool, "reason": str}"""
```

---

## 3. @markup 完备性

### 当前 5 种（不再扩充）

| @函数 | 参数 | 用途 |
|---|---|---|
| `@stat_change` | stat_name, delta, narrative | SAN 损失等属性变化 |
| `@item_gain` | item_name | 获得物品 |
| `@npc_state_change` | npc_name, new_state | NPC 状态变更 |
| `@spawn_enemy` | enemy_ref, scene, quantity | 生成敌人 |
| `@grant_weapon` | weapon_ref, scene, quantity | 生成武器 |

### 不需要的候选

| 候选 | 理由 |
|---|---|
| `@force_move` | `##END_` 和 from_here/to_here 已覆盖场景转移 |
| `@flag_set` | dependency_graph + runtime_state 替代 |
| `@difficulty_set` | escalation 机制已在 Judge 中处理 |
| `@ending_trigger` | `##END_真结局:标签##` 标记已覆盖 |

### side_effects 中的自然语言保留

非机械操作的叙事提示（如"调查员知晓后方已无退路，必须向前"）保留为自然语言字符串，不强制转化为 @markup。

---

## 4. 实现范围

### 改动文件

| 文件 | 改动 |
|---|---|
| `scenario_core.py` | 添加 `NodeRuntimeState` dataclass；`ScenarioWorld` 新增 `runtime_state` 字典，移除 `self.flags`；从 L2 加载 `dependency_graph` |
| `game/judge.py` | `_execute_entity` 写 runtime_state 替代写 flags；`_evaluate_requirement` 重写为 OR 逻辑；新增 `_eval_edge_condition` |
| `game/agents/keeper.py` | `_parse` 的 requirement 评估改用新解析器 |
| `prompts.py` | entity 格式适配新 requirement 结构 |

### 不改动

- `src/llm.py` — `evaluate_failure_penalty` / `evaluate_trait_enhancement` 保持不变
- `scenario_core.py` 中的 `parse_markup_all` / `resolve_graded_result` — 不变
- L2 格式 — 新 JSON 已是目标格式
