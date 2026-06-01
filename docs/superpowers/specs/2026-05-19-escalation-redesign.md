# Escalation & Author 机制重设计

日期：2026-05-19
状态：设计完成
范围：`src/game/escalation.py`（删除）、`src/game/intent_detector.py`（新建）、`src/game/agents/author.py`（重构）、`src/game/agents/keeper.py`（重构）、`src/game/messages.py`（更新）、`src/module_designer/supplement_pipeline.py`（新建）、`src/scenario_core.py`（`wr0_enabled`）

## 动机

当前 escalation 机制有三个核心问题：

1. **每回合无条件 LLM 评估**（O1）— 无论玩家输入是否有 entity 匹配，都调用一次 flash 模型评估三个维度 severity + 三条自然语言规则。触发率极低，浪费率极高。

2. **两套独立触发路径** — 维度评分（LLM 打分 + threshold）和自然语言规则（LLM 判断），逻辑重复，语义重叠。

3. **StructuralEdit 是空壳** — 四字段一个类想产出新场景+新结局+L3调整+依赖边，从未实现，设计上也不现实。

## 核心设计决策

### 触发统一化：Parse other → IntentDetect → Author

```
旧：每回合 LLM 评分(3维度+3规则) → 超阈值 → Author
新：Parse 命中 other → IntentDetect(轻量,并行) → 有意义 → Author
```

**优势**：
- 大多数回合 Parse 返回 entity match，other 为空 → 零 overhead
- Parse 一结束就知道 other 内容，IntentDetect 可立即启动，与 Enrich (LLM) 并行，不阻塞主循环
- "玩家做了模组没覆盖的事" 天然就是 other 语义

### Author 两级响应：Patch vs StructuralEdit

| | ModulePatch | StructuralEdit（新设计） |
|---|---|---|
| 触发 | 行为合理但模组未覆盖（"检查座椅底下"） | 行为符合叙事但完全超出模组范围（"与黑暗存在沟通而非逃离"） |
| 修改范围 | 当前场景加 1-3 个 entity | 新场景 + 新 L1/L2/L3 + 可选结局 |
| 实现方式 | Author 一次 LLM 调用 → entities dict | **补充管线**（轻量版模块生成 pipeline） |
| 产出 | `entities[]` + `scene_descriptions{}` | `supplements/<ts>/l1_supp.json + l2_supp.json + l3_supp.json` |
| 集成 | `_integrate_patch` → 递归 process_turn | `_integrate_supplement` → 合并 graph + l1_data + L3 更新 → 递归 process_turn |

### WR0 独立于 Patch/StructuralEdit

- **Patch**：永远在模组框架内，不需要 WR0
- **StructuralEdit**：由 Author 自动判定
- **WR0**：游戏开始时玩家手动选择，存储在 `ScenarioWorld.wr0_enabled`，中途不可更改

| | WR0 off（默认） | WR0 on |
|---|---|---|
| StructuralEdit | 可扩展场景但必须一致于现有世界规则和基调 | 完全自由，可改写规则、结局、L3 |

## 完整数据流

```
Parse(flash)
  ├─ 正常 entity → Judge(确定) → Enrich(flash) → Curate → Narrator
  │
  └─ 有 other ─────────────────────────────────────┐  ← 并行
       │                                              │
       ├─ IntentDetector(flash, light) ─── 并行 ─────┘
       │     │                                        │
       │     ├─ 无意义("唱首歌放松") → 跳过            │
       │     │                                       │
       │     └─ 有意义 → AuthorRequest                   │
       │           {other_texts, intent, reasoning,    │
       │            scene_context}                     │
       │             │                                 │
       │             ↓                                 │
       │           Author(flash, max reasoning)         │
       │             1. 判定级别: patch/structural       │
       │             2. 生成对应内容                     │
       │             │                                 │
       │             ├─ patch → ModulePatch             │
       │             │   → _integrate_patch             │
       │             │   → 递归 process_turn             │
       │             │                                 │
       │             ├─ structural                      │
       │             │   → 补充管线(flash+max reasoning) │
       │             │     Step 1: 3-4 并行 LLM         │
       │             │     Step 2: 组装+验证+@markup     │
       │             │   → supplements/<ts>/             │
       │             │   → _integrate_supplement         │
       │             │   → L3 更新                       │
       │             │   → 递归 process_turn             │
       │             │                                 │
       │             └─ 打回(entities=[]) → 等同无意义    │
       │                                               │
       └─ (等待 Enrich + IntentDetect → 决策 → Curate)  │

### 打回场景的等待时间与游戏体验

Author 打回（返回 `entities=[]`）在三段路径中等待时间最长：

| 路径 | 等待时间 | 发生频率 |
|------|---------|---------|
| 无 other | 0（Enrich 正常完成） | 大多数回合 |
| other → 无意义 | Detector 延迟（~Enrich 时长，两者并行） | 偶尔 |
| other → 有意义 → Author 打回 | Detector + Author 两次 LLM（串行） | 极少 |

最关键的是第三条路径：玩家输入了 "试图说服黑影放我过去"，Detector 判定有意义，启动了 Author → Author 判断违反世界规则 → 打回。此时：
- **等待时间** = Enrich + max(IntentDetect, Enrich) + Author（因为 Author 依赖 Detector 结果，必须串行）
- **玩家体验**：等了更久却被告知 "没什么特别的事情发生"

缓解措施：
1. **Detector 设置合适的 sensitivity** — 宁可漏过也不要误触发。纯 flavor（"唱首歌"）绝不过，边缘 case（"试图说服 NPC"）也倾向不过，真正需要 Author 的是叙事系统完全无法消化的情况
2. **Author 打回时 Keeper 在 outcome 中追加玩家可见提示** — 不是沉默地被吞掉。如："你尝试说服那个存在，但它似乎对你的言语毫无反应"（由 Enrich 阶段的叙事覆盖，不打回静默消息）
3. **打回结果计入 escalate 历史** — 同一意图短时间内不再重复触发 Author
```

### 并行时序

```
Parse ─── Judge(确定,快) ─── ┌─ Enrich(LLM) ──────────┐ ─ 等待 ─ 决策点 ─ Curate/Narrate
  │                            │                        │
  └─ IntentDetect(LLM) ───────┘ (两个 LLM 调用并行)     │
     (Parse 结束即启动)         └─ 决策点等待最慢的 ────┘
```

### 补充管线内部并行

```
Step 1 (全并行，3-4 次 flash+max reasoning):
  1a: 新场景 + interactions + auto_triggers  (类似 Step 2a+2b)
  1b: events + scene_movements               (类似 Step 2b event)
  1c: L1 玩家可见层                          (类似 Step 2c)

Step 2 (1 次调用):
  2: 交叉核对 + dependency + @markup 标准化   (类似 Step 3b+Phase2)
```

Step 1 的子步之间无依赖（输入都是同一玩家意图 + L3），可以完全并行。

## 组件设计

### IntentDetector（新建 `src/game/intent_detector.py`）

轻量 LLM 判断 other 行为是否有实际叙事意图。

```python
@dataclass
class IntentResult:
    needs_author: bool
    intent: str = ""       # 一句话描述玩家想做什么
    reasoning: str = ""    # 为什么需要升级（而非纯角色扮演）

class IntentDetector:
    def detect(self, other_text: str, world_snapshot: dict) -> IntentResult:
        """调用 flash 模型，极简 prompt，只做 yes/no + 一句话描述."""
```

Prompt 原则：极短。只判断 (1) 纯 flavor 还是真有叙事意图 (2) 有意图的话玩家想达成什么。

### AuthorRequest（更新 `src/game/messages.py`）

```python
@dataclass
class AuthorRequest:
    other_texts: list[str]       # 本轮 other 条目原文
    intent: str                  # Detector 输出
    reasoning: str               # Detector 输出
    scene_context: dict          # Keeper 从 world 提取

@dataclass
class ModulePatch:
    entities: list[dict]             # patch 级新 entity（L2 dict 格式）
    scene_descriptions: dict[str, str]  # 场景描述更新
    justification: str = ""

@dataclass
class StructuralEdit:
    """不再作为 Author 直接产出。Author 判定 structural 后触发补充管线。
    保留此 dataclass 用于综合管线产出的结构。"""
    supplement_path: str            # supplements/<ts>/ 路径
    l3_updates: dict                # L3 调整内容
    entry_scene: str                # 入口场景
    exit_scene: str = ""            # 出口场景（可选）
    justification: str = ""
```

### Author（重构 `src/game/agents/author.py`）

```python
class Author:
    def __init__(self, l3_data):
        self.l3_data = l3_data

    def handle_request(self, request: AuthorRequest) -> ModulePatch | StructuralEdit:
        """1. LLM 判定 patch/structural 级别
           2. 生成对应内容
           3. 返回 ModulePatch 或 StructuralEdit"""
```

Prompt 结构：
- 输入：L3 意图 + 场景上下文 + 玩家意图 + reasoning + WR0 状态
- 第一步：判定 patch 还是 structural
- 第二步：生成内容（patch → entities；structural → 入口/出口场景 + 新内容简述，触发补充管线）

WR0 感知：Keeper 从 `world.wr0_enabled` 读取，写入 `scene_context`，Author prompt 中注入。

### 补充管线（新建 `src/module_designer/supplement_pipeline.py`）

```python
def run_supplement_pipeline(
    player_intent: str,           # 玩家想做什么
    reasoning: str,               # Detector 升级原因
    base_l3: dict,                # 基础 L3（tone_constraints + world_rules + driving_force）
    entry_scene: str,             # 入口场景名
    exit_scene: str = "",         # 出口场景名（可选）
    output_dir: str = "",         # supplements/<ts>/
) -> dict:
    """轻量补充管线。返回 {"l1": ..., "l2": ..., "l3": ...}。

    Step 1: 并行 LLM 调用（3-4 次 flash+max reasoning）
      1a: 新场景 + interactions + auto_triggers
      1b: events + scene_movements (出入口连接)
      1c: L1 玩家可见层

    Step 2: 组装 + 交叉核对 + @markup 标准化 (1 次调用)
    """
```

产出目录：
```
data/modules/<module_name>/supplements/<timestamp>/
  l1_supp.json       # 新场景的玩家可见层
  l2_supp.json       # 新场景 + entity + dependency
  l3_supp.json       # L3 调整/扩展
```

ID 命名规范：统一使用 `S_` 前缀（`SS1`=场景, `SI1`=interaction, `SAT1`=AT, `SE1`=event），避开基础模块的 ID 空间。

### Keeper 改动（重构 `src/game/agents/keeper.py`）

`_check_escalation` 删除，替换为：

```python
def _handle_uncovered_intent(self, parsed, enrich_future, author) -> AuthorRequest | None:
    """Parse 有 other 时被调用。Detect 与 Enrich 并行。"""

def _integrate_supplement(self, structural_edit: StructuralEdit):
    """集成补充管线产出：
    1. 加载 l2_supp.json → 合并 graph.nodes + graph.events
    2. 在出入口场景添加 from_here/to_here 连接边
    3. 加载 l1_supp.json → 合并 narrator.l1_data
    4. 合并 dependency_graph
    5. 加载 l3_supp.json → 更新 author.l3_data
    6. 初始化新 entity 的 runtime_state
    """
```

### ScenarioWorld 改动

```python
class ScenarioWorld:
    def __init__(self, ...):
        ...
        self.wr0_enabled: bool = False  # 游戏开始时玩家选择，中途不可改
```

## 文件变更汇总

| 文件 | 动作 |
|------|------|
| `src/game/escalation.py` | 删除 |
| `src/game/intent_detector.py` | 新建 |
| `src/game/agents/author.py` | 重构 |
| `src/game/agents/keeper.py` | `_check_escalation`→`_handle_uncovered_intent`；新建 `_integrate_supplement` |
| `src/game/messages.py` | 新建 `AuthorRequest`/`IntentResult`；保留 `ModulePatch`；重定义 `StructuralEdit` |
| `src/module_designer/supplement_pipeline.py` | 新建 |
| `src/scenario_core.py` | 新增 `wr0_enabled` |
| `src/game_loop.py` | `init_game` 增加 WR0 配置传入 |
| `docs/superpowers/specs/NEXT-SESSION.md` | 更新架构描述 |

## 设计取舍

1. **Detector 不区分 patch/structural** — 它只判断 "有意义/无意义"。分级是 Author 的职责，因为只有 Author 掌握 L3 信息，知道玩家意图是 module 缺口还是叙事级偏离。

2. **补充管线只有 2 步** vs 基础 13 步 — 起点是结构化的玩家意图 + L3，不需要去重（全新内容）、不需要风格预判（继承基础 L3）、不需要从 .docx 提取。产出通常 1-3 个场景，复杂度远低于完整模块。

3. **WR0 放 ScenarioWorld** — 而非 Author 实例。因为 WR0 影响的是 "这个世界的创作自由度"，Author 是工具。
