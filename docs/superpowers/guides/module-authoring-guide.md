# 模组创作指南

本指南说明如何为 COC 模拟器编写模组源文档，以及管线会将其转化为什么样的三层数据。面向模组创作者，不假设了解管线内部实现。

---

## 1. 整体架构：三层分离

管线将你的模组文档转化为三层数据，每层面向不同角色：

| 层 | 面向 | 职责 |
|----|------|------|
| **L1 玩家层** | 玩家 | 场景氛围、可感知元素、NPC 外貌——玩家能看到/感受到的一切 |
| **L2 守秘层** | KP（游戏主持） | 互动、事件、自动触发、敌人数据、场景连接——运行时的全部机械 |
| **L3 设计层** | 模组创作者 | 世界规则、场景意图、叙事线、结局条件、基调约束——「为什么这样设计」 |

**你只需要写源文档（docx/txt），管线自动生成 L1/L2/L3。**

---

## 2. 源文档写法

源文档是你用自然语言写的模组故事。管线通过 LLM 理解你的文本并提取结构化数据。

### 2.1 写清楚什么

- **场景边界明确**：每个场景有独立段落，场景切换时写清位置变化
- **NPC 有行为动机**：不只写「有个 NPC 叫 X」，写他为什么在这里、想干什么
- **敌人写清行为逻辑**：不只是「出现一个怪物」，写它的攻击方式和感知条件
- **物品写清位置和用途**：「厨房桌上有一把银餐刀」而非「某处有把刀」
- **关键抉择有后果**：玩家做了 A 会怎样，做了 B 会怎样

### 2.2 不需要写什么

- 不需要写游戏规则数值（STR、CON 等由库数据提供）
- 不需要写 @markup 标记（管线 Phase 2 自动生成）
- 不需要写 dependency 关系（管线 Step 3.5 自动推导）
- 不需要自己编 entity ID（管线统一分配 I1/I2/AT1/E1 等）

### 2.3 测试故事参考

用于快速测试的极小模组（管线约 2-3 分钟跑完）：

```
林中小屋

暴风雨夜，调查员迷路后找到一间亮灯的森林木屋。

开门的是中年妇人艾米丽。她收留调查员过夜，
但指着客厅尽头钉死的门警告："地下室别去，
我丈夫在下面——他已经不是人了。"

木屋客厅有壁炉和一张旧沙发，厨房桌上放着一把银餐刀。
通往地下室的门被木板封住，但木板已松动。

地下室里，艾米丽的丈夫已变成食尸鬼，正在啃食动物残骸。
墙角还有两只受惊的巨型老鼠，会主动攻击入侵者。

食尸鬼察觉生人气味后会冲破木板闯入客厅。
艾米丽哀求不要伤害丈夫——诅咒只能用银器破除。

暴风雨愈发猛烈，闪电不断击中屋外树木，木屋随时可能倒塌。
```

**规模对照**：「林中小屋」2 场景 / 1 NPC / 1 Boss / 1 普通敌人；「常暗之厢」7+ 场景 / 3+ NPC / 多层叙事线。

---

## 3. 三层数据各有什么

### 3.1 L1 玩家层

管线为每个场景生成：

| 字段 | 说明 |
|------|------|
| `description` | 场景描述 |
| `atmosphere` | 氛围 |
| `mood` | 情绪基调（confused/uneasy/tense/terrified/hopeful/desperate） |
| `perceptible` | 可无条件感知的元素列表（name + brief + 类型） |
| `ambient_hints` | 环境暗示，如"远处低沉的咀嚼声" |
| `npc_appearances` | NPC 外貌 + 神态 |

### 3.2 L2 守秘层

四种 entity 类型：

**Interaction（互动）**：玩家主动触发的动作。包含触发条件、需求、结果、副作用、技能检定难度。

**Event（事件）**：全局事件，不绑定特定场景。条件满足时自动触发。

**Auto-trigger（自动触发）**：场景级被动事件。玩家进入场景或满足条件时自动激活。

**Boss Encounter（Boss 战）**：从 `boss_hints`（Step 1a 提取）和 Boss 库匹配生成，含触发方式和需求。

L2 还包含：
- **scene_movements**：场景间通行路径（from_here / to_here）
- **npc_profiles**：NPC 能力、互动触发条件、性格、初始状态
- **dependency_graph**：entity 间依赖关系
- **encounters / scene_weapons**：遭遇配置和场景武器

### 3.3 L3 设计层

| 字段 | 说明 |
|------|------|
| `module_meta` | 标题、时代、主题、预计时长、玩家数 |
| `world_rules` | 世界运行规则（物理/超自然法则） |
| `scene_intents` | 每个场景的设计目的、核心威胁 |
| `ending_conditions` | 结局条件 + 叙事描述 |
| `tone_constraints` | 体裁、禁止元素、推荐元素、叙事风格 |
| `characters` | 每个 NPC 的设计意图和行为逻辑 |
| `driving_force` | 一切事件的底层驱动力 |
| `narrative_lines` | 故事大纲和叙事线（可多条，主线/支线/可选） |
| `time_pressure` | 时间压力配置（可选） |

---

## 4. @markup 系统（7 种）

Phase 2 自动将自然语言转化为结构化副作用标记。你在写源文档时只需用自然语言描述后果，管线会处理转化。

| 标记 | 用途 | 示例 |
|------|------|------|
| `@spawn_enemy(enemy_ref, scene, quantity)` | 生成敌人 | 食尸鬼冲破木板时 |
| `@grant_weapon(weapon_ref, scene, quantity)` | 场景中出现武器 | 消防斧靠在墙边 |
| `@stat_change(stat_name, delta, narrative)` | 属性变化 | 目睹恐怖场景 SAN-1 |
| `@item_gain(item_name, quantity)` | 获得物品 | 抽屉里找到钥匙 |
| `@consume_item(item_name, quantity, narrative)` | 消耗物品 | 用银餐刀解除诅咒 |
| `@npc_state_change(npc_name, new_state)` | NPC 状态变化 | 艾米丽陷入绝望 |
| `@npc_follow(npc_name, follow)` | NPC 跟随/离队 | 艾米丽跟随调查员 |

---

## 5. 敌人与 Boss 设计

### 5.1 敌人库（普通敌人）

位于 `data/library/core/enemies.json`。每个敌人有属性、护甲、攻击方式、特殊能力、SAN 损失和 `combat_behavior`。

**combat_behavior 支持 flag 前缀**（管道符分隔）：

| Flag | 效果 |
|------|------|
| `[adjacent_aware]` | 跨场景可感知（如大嘴吞噬者的振动感知） |
| `[avoidable]` | 可非战斗绕过，触发对峙阶段（语义匹配→D100 检定） |

示例：`[adjacent_aware] | 优先攻击发出最大声音的目标。被击伤后狂暴。`

### 5.2 Boss 库

位于 `data/library/core/bosses.json`。Boss 有数值 + `boss_mechanics`（击败方式/弱点描述）和 `flags: ["boss"]`。

**写作要点**：在源文档中暗示 Boss 的存在即可——Step 1a 会提取 `boss_hints`，Step 2 Boss 管线会用 LLM 将其与 Boss 库匹配并生成完整的 Boss Encounter。

---

## 6. NPC 设计

NPC 在源文档中出现后，管线通过三层描述：

- **L3 `characters`**：设计意图——为什么这个 NPC 存在？行为逻辑是什么？
- **L2 `npc_profiles`**：能力 + 触发条件 + 初始状态（state/attitude/following）
- **L1 `npc_appearances`**：外貌 + 神态

**写作要点**：写清 NPC 的动机和行为倾向，而非只描述外貌。例如「艾米丽想保护丈夫，但知道他已经不可挽回」比「艾米丽是个中年妇人」更有用。

---

## 7. 时间压力

如果模组有倒计时、追逐、环境吞噬等时间威胁，在源文档中写清：

- 威胁的本质（什么在逼近？）
- 节奏（什么时候加速？）
- 信号（玩家如何感知威胁加剧？）

管线 Step 2c L3 会提取为 `time_pressure` 字段。如果模组没有时间威胁，管线会留空——不要硬塞。

---

## 8. 叙事线

管线会从源文档中提取 `narrative_lines`，每条含：

- `name`：叙事线名称
- `outline`：大纲（起承转合、关键转折点）
- `key_scenes`：涉及场景
- `type`：`main`（主线）/ `branch`（支线）/ `optional`（可选支线）

至少有一条 `main` 主线。复杂模组可设计多条叙事线（如主线「逃离常暗之厢」+ 支线「解救乘务员」）。

---

## 9. 结局条件

写源文档时，暗示可能的结局方向即可。管线会提取具体的 `ending_conditions`（END1/END2...），运行时通过 `##END_` 标记触发。

---

## 10. 写作检查清单

- [ ] 每个场景有明确的物理边界和氛围
- [ ] 每个 NPC 有行为动机
- [ ] 每个敌人有 combat_behavior（攻击逻辑、何时进攻）
- [ ] 关键物品写清位置
- [ ] 重要抉择有多种可能后果
- [ ] 如有时间威胁，写清了节奏和信号
- [ ] 故事有明确的主线和结局方向
- [ ] 源文档长度适中：测试模组 200-500 字，完整模组 2000-5000 字

---

## 11. 运行管线

```bash
# Jupyter 调试（推荐，可看到每步中间结果）
# 打开 notebooks/parser_layered.ipynb，逐个 Cell 执行

# 或命令行自动运行
PYTHONPATH="src" python run_pipeline.py --auto
```

产物输出到 `data/modules/<模组名>/l1_player.json`、`l2_keeper.json`、`l3_designer.json`。
