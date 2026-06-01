# Pre-Parse Disambiguator Design

**日期**: 2026-05-27
**状态**: 设计完成，待用户审阅

---

## 问题

当前 Parse 对模糊输入（"搜一下""跟他聊聊""去那边""那个"）会强行匹配 entity，导致误报（flavor text 被当成有意义行动）或匹配错误。现有 IntentDetector 是 post-parse 二元判定（has_intent yes/no），无法解决"匹配了但匹配错了"的问题。

## 方案概览

在 Parse 前插入轻量 **Pre-Parse Disambiguator**（flash 模型），与 Parse 并行执行。仅做消歧一件事。

```
Turn 开始
  ├─ Pre-Parse (flash) ──────┐
  └─ Parse (主模型) ─────并行──┤
                               ↓
                  两者都完成后：
                    clear → 执行 Parse 结果（零额外延迟）
                    ambiguous → 丢弃 Parse 结果，向玩家展示反问
                      └─ 玩家重输入 → 新 turn（pre-parse 携带上轮上下文）
```

## 核心机制

### 两路输出

| 判定 | 行为 |
|------|------|
| `clear` | Parse 结果照常执行 |
| `ambiguous` | 阻断执行，生成自然语言反问；丢弃 Parse 结果 |

### 跨 Turn 上下文整合

pre-parse 维护轻量上下文（上一轮模糊输入摘要 + 已提出的反问），新 turn 收到玩家澄清后尝试整合：

```
Turn N:   玩家 "搜一下"
          → ambiguous, 缓存 context: {prev: "搜一下", asked: "你想搜查什么？"}
          → 反问 "你想搜查什么？"

Turn N+1: 玩家 "抽屉" + context
          → pre-parse 整合为清晰意图
          → clear → Parse 正常执行
```

### 并行模式

pre-parse 和 Parse 同时启动。clear 路径下 pre-parse 判定和 Parse 生成并行完成，零额外延迟。ambiguous 路径下 Parse 结果被丢弃——浪费一次主模型调用，但 ambiguous turn 占比低。

## 接口

### 输入

| 字段 | 来源 | 说明 |
|------|------|------|
| `player_text` | 玩家原始输入 | 当前 turn 文本 |
| `ambiguity_context` | pre-parse 自身状态 | 上轮模糊输入摘要 + 反问（无上一轮则为空） |
| `world_brief` | Keeper | 当前场景名 + 可用互动名列表 + NPC 名列表 + 出口（≤200 tokens） |

### 输出

```json
{
  "clarity": "clear" | "ambiguous",
  "interpretation": "对玩家意图的解读",
  "resolved_text": "仅 clear 且有跨轮上下文整合时填入——将上下文与本轮输入合并为完整行动描述。如'搜一下'+'抽屉'→'搜查抽屉'。无上下文整合则留空",
  "question": "当 ambiguous 时，自然语言反问，附带1-2个示例"
}
```

- `interpretation`：always set。clear 时用于日志追踪消歧结果
- `question`：仅 ambiguous 时填入。自然语言开放式反问，**附带 1-2 个简短示例引导玩家回答**，不做结构化选项

### 反问格式（引导玩家）

反问应包含：简短说明为什么模糊 + 1-2 个具体示例，让玩家知道怎么回答：

> "搜查哪里？比如你可以说'检查抽屉'、'翻找柜子'"
> "你想和谁说话？比如'乘务员'、'车厢里的乘客'"

注意：示例是提示作用，不限制玩家输入。玩家可以输入示例之外的内容。

### 消歧原则（注入 system prompt）

一个清晰的行动需同时满足：**动作 + 目标对象**。缺少任一为模糊。

- 指代不明："跟他聊聊"（谁？）→ 反问涉及的 NPC/对象
- 缺目标："搜一下"（搜什么？）→ 反问搜索对象
- 缺动作：仅在玩家提到具名对象但无动作时判定模糊（如仅说"那个抽屉"）

### Prompt 管理

`build_pre_parse_prompt()` 集中定义在 `src/prompts.py`，与现有 Keeper/Narrator/Author prompt 管理方式一致。system prompt 包含消歧原则 + 反问格式要求。

## 与现有组件的关系

| 组件 | 变化 |
|------|------|
| Parse | **不改** |
| IntentDetector | **不变** |
| Keeper | 增加 pre-parse 结果等待逻辑，ambiguous 时阻断并反问 |
| Author | **不变** |

## 实现要点

1. pre-parse 在 `process_turn` 入口与 Parse 并行启动（ThreadPoolExecutor）。Parse 用原始 raw text
2. Parse 完成后的执行逻辑增加 gate：等 pre-parse 判定 → clear 才放行
3. clear 且 `resolved_text` 不为空时，用 `resolved_text` 替代 raw 作为 Parse 输入（跨轮整合）
4. ambiguous 时 Keeper 直接返回反问文本给前端，不触发 Judge/Enrich/Author
5. 反问后玩家输入在新 turn 中携带 `ambiguity_context` 重新进 pre-parse
6. 连续 ambiguous 上限 2 次，第 3 次强制按 clear 处理（兜底）

## 规模

- 新增 `src/game/pre_parse.py`（~80 行）
- `src/prompts.py` 增加 `build_pre_parse_prompt()`（~50 行）
- `src/game/agents/keeper.py` 增加并行编排 + gate 逻辑（~30 行）
- `src/game/messages.py` 增加 `PreParseResult` dataclass

## 风险与权衡

- **ambiguous turn 浪费一次 Parse 调用** — 可接受，ambiguous 占比低，且替代方案（pre-parse 完成后才启动 Parse）会让 clear 路径延迟翻倍
- **连续追问体验** — 2 次上限 + 第 3 次强制推进，避免死循环
- **跨 turn 上下文膨胀** — context 仅保留上轮摘要 + 反问，不累积历史
