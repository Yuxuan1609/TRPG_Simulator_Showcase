# 法术体系设计

> 状态：设计完成，待实现。2026-05-27 脑洞产出。

## 1. 法术双层架构

| 类型 | 介入路径 | 规则方式 | MVP |
|------|----------|----------|-----|
| 战斗法术 | Investigator + CombatSystem 直接调用 | 确定性 D100 + 伤害公式 | ✅ |
| 轻量探索法术 | 关键词短路 → SpellJudge → Author Patch → 注回 parse | 约束确定性 / 后果 LLM | ✅ |
| 重探索法术 | 同上，但 Author 需走重量级重生成管线 | 依赖世界状态拼接（远期） | ⏸ 延期 |

**界限判定**：轻量探索法术只读不写——可以感知、获取信息、产生叙事输出，不修改已有 entity/关系/NPC 状态/场景描述。结果以 narrator 文本输出，不产生 @markup 副作用。

**设计参考**：法术系统更多参考克苏鲁小说而非 COC 7th 规则书——探索法术的文学性描述优先于机械规则。

## 2. 法术库 `spells.json`

路径：`data/library/core/spells.json` + `data/library/extensions/`（复用现有武器/敌人库扩展模式）

```json
{
  "spells": [
    {
      "id": "HEART_ARREST",
      "name": "心脏骤停",
      "category": "combat",
      "cost": {"mp": 12, "san_permanent": 1},
      "time": "1轮",
      "check": {"skill": "POW", "type": "opposed"},
      "effect_type": "damage",
      "effect_detail": "目标 POW 对抗失败则受到 1D6+DB 伤害，无视护甲",
      "constraints": {"range": "视线内", "materials": []},
      "weight": "light"
    },
    {
      "id": "LIFE_DETECTION",
      "name": "生命觉察",
      "category": "exploration",
      "cost": {"mp": 3, "san_permanent": 0},
      "time": "1轮",
      "check": {"skill": "POW", "type": "regular"},
      "effect_type": "perception",
      "effect_detail": "感知场景内所有活物的位置和大致状态，持续 1 轮",
      "constraints": {"range": "当前场景", "materials": []},
      "weight": "light"
    }
  ]
}
```

关键字段：

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识，供 `@grant_spell` 和法术库查找 |
| `category` | `combat` / `exploration` |
| `cost` | MP + SAN 永久损失（临时 SAN 扣减由检定结果决定） |
| `time` | 施法时间（轮/分钟），影响 TimeAgent 评估 |
| `check` | 检定技能 + 类型（regular/hard/opposed） |
| `effect_type` | damage / buff / summon / perception / insight / debuff |
| `effect_detail` | 叙事效果描述模板 |
| `constraints` | 材料/范围/环境等硬性条件 |
| `weight` | `light`（MVP 可用）/ `heavy`（延期） |

`SpellLibrary` 类：加载核心库 + 扩展，提供 `get(id)` / `list_by_category(category)` / `list_by_weight(weight)`。

## 3. Investigator 法术存储

`src/investigator/models.py` 新增：

```python
class Investigator:
    known_combat_spells: list[str]     # spell_id 列表
    known_exploration_spells: list[str]
```

法术获取通过 `@grant_spell` side effect（第 8 种 @markup，见 §5）。

## 4. SpellJudge 独立类

类似 CombatSystem——Keeper 通过接口调用，SpellJudge 内部闭环。

### 接口

```
SpellJudge.resolve(raw, world, author, spell_library)
  → {"spell_triggered": bool, "parse_action": dict | None, "narrative": str}
```

### 内部流程

```
player_input → KeywordDetect("法术"/"施法"/"咒"/"念诵"...)
  → 短路 Keeper 主 parse/judge/enrich/curate/narrator 管线
  → Step 1: 识别法术
      parse 玩家输入 → 模糊匹配 spells.json 中的法术 name/id
  → Step 2: 硬约束检查（确定性）
      - 已知法术检查：spell_id in Investigator.known_xxx_spells
      - MP 检查：player.mp >= spell.cost.mp
      - 材料检查：player.has_item(material)
      - 环境约束：range / scene / time_of_day 等
      → 不满足 → 直接返回失败消息，不调 Author
  → Step 3: 扣减前置代价
      player.mp -= cost.mp; player.modify_stat("SAN_max", -cost.san_permanent)
  → Step 4: 打包 → Author
      {spell_name, effect, need_check, skill, success_desc, fail_desc} → AuthorRequest
  → Step 5: Author 返回 Patch → Keeper._integrate_patch()
  → Step 6: 构造 parse action
      将 Author 返回的 entity 结果 + 确定性语言包装 → {"type": "interaction", "id": "SPELL_XXX", ...}
  → 注回 enrich→curate→narrator 管线输出
```

### 在 Keeper 中的接入点

`Keeper.process_turn()` 的最顶部，在 `_inject_npc_at()` 之前（或紧随其后）：

```python
if self.spell_judge:
    spell_result = self.spell_judge.resolve(raw, self.world, author, self.spell_library)
    if spell_result["spell_triggered"]:
        # 短路主管线，spell_judge 内部已处理所有步骤
        return _build_spell_turn_result(spell_result)
```

### Keeper 初始化

```python
self.spell_judge = SpellJudge()           # 独立实例
self.spell_library = SpellLibrary("data/library/core/spells.json")
```

## 5. 第 8 种 @markup：`@grant_spell`

### 格式

```
@grant_spell(spell_ref="HEART_ARREST")
@grant_spell(spell_ref="LIFE_DETECTION", category="exploration")
```

### Side Effect Dataclass

`src/game/side_effects.py` 新增：

```python
@dataclass
class GrantSpell:
    spell_ref: str
    category: str = ""  # "combat" | "exploration"，空则从库推断
```

### 应用路径

`Keeper._apply_side_effects()` 新增分支：

```python
elif isinstance(effect, GrantSpell):
    spell = self.spell_library.get(effect.spell_ref)
    if not spell:
        msgs.append(f"[获得法术] {effect.spell_ref}（库中未找到）")
    else:
        cat = effect.category or spell.category
        if cat == "combat":
            self.world.player.known_combat_spells.append(effect.spell_ref)
        else:
            self.world.player.known_exploration_spells.append(effect.spell_ref)
        msgs.append(f"[获得法术] {spell.name}")
```

### @markup 解析

`_MARKUP_PATTERN` 新增 `grant_spell`，`_build_side_effect()` 新增对应分支。

## 6. 战斗法术 — CombatSystem 集成

战斗法术直接挂到 Investigator 和 CombatSystem，不走 SpellJudge。

### 施法动作

`CombatSystem._process_round()` 新增 action_type `"cast_spell"`：

```python
# 玩家施法
if action_id == "cast_SPELL_ID":
    spell = spell_library.get("SPELL_ID")
    if not self._can_cast(spell, player):
        return CombatAction(actor="player", action_type="cast_spell", 
                           success=False, narrative="MP不足或法术未知，施法失败")
    # 扣 MP
    player.mp -= spell.cost.mp
    # 法术检定
    ok, msg, tier = _resolve_spell_check(spell, player, target)
    # 伤害/效果
    if spell.effect_type == "damage":
        damage = _roll_damage(spell.effect_params.get("formula", "1D6"), STR, SIZ)
        # ... 护甲减免等
```

### 玩家 action_id 构造

前端/CLI 战斗回合中，玩家可选动作包含已知战斗法术：

```
可选动作：[攻击 / 闪避 / 逃跑 / 施法:心脏骤停 / ...]
```

## 7. 模组生成管线修改

### Step 1a（结构化提取）

源文档出现法术相关描述时，LLM 输出新增 `spell_refs` 字段：

```json
{
  "scenes": {"车厢内部": {"spell_refs": [], ...}},
  "items": [{"name": "《死灵书》残页", "spell_refs": ["HEART_ARREST"]}],
  ...
}
```

`spell_refs` 引用的 ID 必须在 `spells.json` 中存在（管线后处理验证）。

### Phase 2（@markup 标准化）

将 Step 1a 产出的 spell_refs 转为 `@grant_spell` 标记，嵌入相关 entity 的 side_effects：

```
// entity "I_READ_NECRONOMICON"
result: "你翻阅了残页，@grant_spell(spell_ref=\"HEART_ARREST\") 一行古老的咒文映入你的脑海..."
side_effects: ["@grant_spell(spell_ref=\"HEART_ARREST\")"]
```

### Step 3b（交叉核对）

新增检查：验证所有 `@grant_spell` 引用的 spell_ref 在法术库中存在。不存在的报 warning。

## 8. 模组生成 prompt 修改点

| 步骤 | 修改 |
|------|------|
| Step 1a user prompt | 追加法术库摘要（法术名称 + 简短效果，≤500 chars），要求匹配时引用 `spell_id` |
| Step 2a user prompt | 法术触发交互纳入 entity 生成考量 |
| Phase 2 system prompt | `grant_spell` 加入 @markup 列表 |
| Step 3b | 法术库交叉校验 |

## 9. 局末成长（远期设计接口）

结局触发后，LLM Epilogue Judge 基于局内经历摘要做角色成长审判：

```json
{
  "permanent_changes": [
    {"type": "grant_spell", "spell_ref": "xxx"},
    {"type": "stat_change", "stat_name": "POW", "delta": 5},
    {"type": "add_skill_points", "skill": "Cthulhu Mythos", "points": 10}
  ],
  "narrative": "经历了这一切，你不再是从前的自己..."
}
```

此功能与 U7（跨模组持久化）属于同一问题域，待世界状态拼接功能完成后设计实现，不在 MVP 范围。

## 10. 文件变更清单

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `data/library/core/spells.json` | 新建 | 核心法术库 |
| `src/library/spells.py` | 新建 | SpellLibrary 类 |
| `src/game/spell_judge.py` | 新建 | SpellJudge 独立类 |
| `src/game/side_effects.py` | 修改 | 新增 GrantSpell dataclass + @grant_spell 解析 |
| `src/game/agents/keeper.py` | 修改 | 集成 SpellJudge、法术关键词检测 |
| `src/investigator/models.py` | 修改 | Investigator 新增 known_combat_spells / known_exploration_spells |
| `src/game/combat.py` | 修改 | CombatSystem 新增 cast_spell 动作 |
| `src/module_designer/layered_parser.py` | 修改 | Step 1a/Phase 2/Step 3b 法术感知 |
| `src/module_designer/layered_pipeline.py` | 修改 | 法术验证步骤 |
