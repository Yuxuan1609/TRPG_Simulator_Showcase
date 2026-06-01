# 战斗系统文档 v2

> 最后更新：2026-05-29

## 架构概览

```
player input → keeper.process_turn()
    ├─ enemy detection(LLM)  → combat_init
    │   └─ 前置：get_combat_context(scene) → 有敌人且 status∉(dead,defeated) 才继续
    ├─ boss "at"/"interaction" check  → merged into same combat_init
    │   └─ 若已有普通敌人 CombatInit，Boss 合并进去，不覆盖
    ├─ boss "event" check  → combat_init
    └─ return {..., "combat_init": CombatInit}

caller(receives combat_init)
    ├─ CLI(run_game.py)  → _run_interactive_combat()
    │   └─ 每轮: 动作选择(含 player_extra 输入)
    │       → _resolve_player_action → _resolve_enemy_action
    │       → _llm_correct_round(玩家) + _llm_correct_enemy_round(敌人子agent)
    │       → 显示修正结果 → 结算伤害 → 下一轮
    │       → 战斗结束：exit_combat({outcome}) + 写 text log + LLM 叙事
    └─ Frontend(game.py)  → CombatSystem.run_combat()(auto-combat)
```

## 群组模型（"以群为单位"）

敌人以 **群组(group)** 为单位管理，而非个体实例。一个群组由三元组 `(scene, enemy_ref)` 唯一标识。

```
群组 = { scene + enemy_ref }  →  quantity, status
```

### spawn 合并

```python
spawn(enemy_ref, scene, quantity)
  → 查找 (scene, enemy_ref) 是否已存在群组
    ├─ 存在：quantity 叠加，HP 重新计算（(CON+SIZ)//10 × 新 quantity）
    └─ 不存在：新建群组
```

- 同一个场景下所有同类敌人属于同一个群组
- 不同 enemy_ref 属于不同群组，行为独立
- quantity 只在进入战斗后才体现（展开为独立实体）

### 数量展开

`_init_combat()` 将 `quantity > 1` 的群组展开为独立战斗实体：

```python
# 群组 quantity=3, hp=30 → 3 个独立实体，每个 hp=10, instance_id 后缀 _c0/_c1/_c2
for e in combat_init.enemies:
    qty = max(1, getattr(e, 'quantity', 1))
    per_hp = getattr(e, 'hp', 10) // qty
    for i in range(qty):
        ce = copy.copy(e)
        ce.instance_id = f"{e.instance_id}_c{i}"
        ce.hp = per_hp
        ce.quantity = 1
```

展开后的 `_cN` ID 仅用于战斗流程，战斗结束后丢弃，不需要映射回群组。

### ≥5 敌人处理

`CombatInit.__post_init__` 自动截断 `enemies` 到 5 个。赢则所有参战群组 defeat，无 partial survival。

## 入口接口

### CombatInit (`src/game/messages.py`)

```python
@dataclass
class CombatInit:
    enemies: list          # 敌人 EnemyInstance 列表(max 5, 自动截断)
    player: Investigator   # 调查员对象
    scene: str             # 战斗场景名
    initiative_context: str
    environment_actions: list[dict]  # 场景环境动作
    player_action: str     # 预设动作(空=默认 punch)
    player_targets: list[str]        # 多目标 ID 列表
    player_extra: str      # 额外意图描述(如"攻击核心")
```

### CombatResult (`src/game/messages.py`)

```python
@dataclass
class CombatResult:
    outcome: str                  # "win" | "loss" | "flee" | "draw"
    defeated_instance_ids: list   # 保留字段(当前不再使用)
    narrative: str
    player_hp: int
    player_san: int
    rounds: int
    round_log: list
```

## 玩家可执行动作

| 动作 | ID | 机制 |
|------|-----|------|
| 攻击 | `weapon:xxx` / `punch` / `kick` | D100 vs skill → `_roll_damage` → `_apply_armor` → `_apply_damage_multiplier` |
| 回避 | `dodge` | `_player_dodging=True`，下一击敌人自动 miss |
| 逃跑 | `flee` | DEX vs 敌人最大 DEX，成功→退出战斗(**不清理敌人**) |
| 隐蔽 | `conceal` | 潜行检定，成功→下次攻击命中 +10 |
| 瞄准 | `aim` | 必成功，下次攻击命中 +20 |
| 蓄力 | `charge` | 必成功，下次攻击伤害 ×1.5 |

隐蔽/瞄准/蓄力可叠加；只消耗于下一次攻击。武器 `multi_attack` 控制每轮攻击次数，每击可指定不同目标。

**player_extra**：攻击选定武器和目标后，可输入额外意图描述（如"攻击核心"）。仅在 `special_rules` 相关时被 LLM 使用，常规战斗无视。

## 战斗结果处理

### exit_combat 简化（outcome 驱动）

```python
def exit_combat(self, result: dict):
    outcome = result.get("outcome", "")
    if outcome == "win":
        for iid in self._combat_enemies:
            inst = self._instances.get(iid)
            if inst:
                inst.status = "defeated"    # 群组被击败
    else:
        for iid in self._combat_enemies:
            inst = self._instances.get(iid)
            if inst and inst.status == "engaged":
                inst.status = "hostile"     # 恢复敌对
    self._combat_enemies.clear()
    self._combat_active = False
```

不再依赖 `defeated_instance_ids`。赢则全部 defeat，非赢则恢复 hostile。

| 结果 | 敌人处理 | Boss 处理 | 游戏结束 |
|------|---------|----------|---------|
| win | status → "defeated" | resolve_outcome + mark_completed | 否 |
| loss（普通敌人） | 恢复 hostile，**游戏结束** | — | **是** |
| loss（Boss 战） | 恢复 hostile，游戏继续 | resolve_outcome（不 mark） | **否** |
| draw | 恢复 hostile | 同上 | 否 |
| flee | **不清理敌人/Boss** | 只清 active，不 resolve | 否 |

### Boss 判定

只要 `CombatInit.enemies` 中存在 `boss_mechanics != ""` 的敌人，或有 `world.bosses.active_boss_id`，即为 Boss 战斗。被 Boss 击败不会导致游戏结束。

### 一回合一次战斗

同一回合内，普通敌人和 Boss 合并到**同一个 CombatInit**。不会分开触发两次战斗。

## 战斗日志

### 文本格式 (.txt)

每场战斗结束后写入 `logs/prompt_log_<ts>/combat_log_<ts>_r<N>.txt`：

```
战斗日志
场景: 5号车厢
调查员: 张弛
回合数: 3
结果: win
HP: 10/12  SAN: 55/60

============================================================
[R01] 调查员 | attack | 格斗=50 | D100=34 hard | 伤害=100 物理 HP10→-90
[R01] Clicker_c0 | attack | 格斗=40 | D100=78 failure | 伤害=0
...
============================================================
```

数据来自 `state.full_log`，由于 Python 对象共享引用，LLM 修正后的 damage 值自动反映在日志中。

### LLM 叙事 prompt/response

`_generate_combat_narrative` 调用后，prompt 和 response 保存到同一目录：
- `combat_narrative_<ts>_prompt.txt`
- `combat_narrative_<ts>_response.txt`

## 武器系统

### damage 结构化格式

```json
{
  "dice_n": 1,      // 骰子数量(0 表示无骰值)
  "dice_d": 6,      // 骰子面数 → 1D6
  "bonus": 0,       // 固定加值
  "use_db": true    // 是否加伤害加深(STR+SIZ)
}
```

`_roll_damage` 兼容旧字符串格式(`"1D6+DB"`)、None/空值(fallback → 0)、dict 格式。由 `_parse_legacy_damage` 自动转换。

### Weapon 类 (`src/investigator/models.py`)

```python
class Weapon:
    name: str
    skill_name: str = "格斗"
    damage: str = "1D3+DB"       # 基础伤害(字符串兼容)
    range: str = "接触"
    damage_type: str = "物理"
    armor_piercing: int = 0
    attack_bonus: int = 0
    multi_attack: int = 1
    special_rules: str = ""       # LLM 修正规则文本
```

**注意**：拾取武器时必须从 `LibraryWeapon` 复制全部字段（含 `special_rules`/`damage_type`/`multi_attack`），否则 LLM 修正和伤害倍率无效。使用 `_wattr()` 辅助兼容 dict 和 dataclass。

## 敌人系统

### LibraryEnemy.status 配置

```python
@dataclass
class LibraryEnemy:
    status: str = "hostile"  # "hostile" | "neutral"
```

`spawn()` 从 `lib_enemy.status` 读取。默认 `"hostile"`。战斗入场检测过滤 `("dead", "defeated")`。

### EnemyAttack 结构化

```python
@dataclass
class EnemyAttack:
    name: str           # "噬咬"
    damage: dict        # 同武器 damage 格式
    skill_name: str     # "格斗"
    skill_value: int    # 命中技能值
    weight: int         # 权重(越高越优先)
```

`.get()` 方法兼容 dict 访问（`attack.get("name")`）。

### 敌人实例字段

| 字段 | 说明 |
|------|------|
| `instance_id` | 群组唯一 ID |
| `enemy_ref` | 库引用名 |
| `scene` | 所在场景 |
| `quantity` | 群内敌人数量（战斗时展开） |
| `status` | "hostile" / "neutral" / "engaged" / "defeated" |
| `attributes` | STR/CON/SIZ/DEX/POW |
| `armor` | 护甲值(如"2点厚皮") |
| `damage_multipliers` | 伤害倍率(如`{"火焰": 2.0}`) |
| `multi_attack` | 每轮攻击次数 |
| `phases` | 阶段触发(hp_below_pct / round) |
| `special_rules` | LLM 修正规则文本 |
| `boss_mechanics` | Boss 特殊机制描述 |

**Boss 攻击配置**：若 Boss 攻击使用特殊效果（POW/SAN 损失等非物理伤害），必须在 `special_rules` 中描述具体效果，否则 `_roll_damage` 返回 0。

### EnemyManager 关键方法

```python
spawn(enemy_ref, scene, quantity) → 合并到已有群组或新建
register(instance)                 → 注册外部 EnemyInstance（如 Boss）
add_to_combat(instance_id)        → 将实例加入当前战斗列表
enter_combat(instance_ids)        → 标记群组为 "engaged"，存储原始 ID 列表
exit_combat({"outcome": ...})     → outcome 驱动：win → 全 defeat，否则恢复 hostile
```

## LLM 修正系统

### 玩家伤害修正 (`_llm_correct_round`)

触发条件：`_any_special_rules()` 返回 True(武器或敌人有 `special_rules`)

**Prompt 结构(自然语言)：**

```
【调查员背景】
调查员A: 退役士兵，左腿有旧伤...

【本轮额外意图】
攻击Boss核心(仅在有特殊规则且意图匹配时生效)

玩家使用「试作型裁决者」发动攻击：
第1击: 试作型裁决者 → Clicker | D100=45 → regular | 原始伤害0(物理)

【武器特殊规则】
试作型裁决者: 直接造成100点伤害，无视护甲和伤害倍率

【目标/在场敌人特殊规则】
Clicker: 受伤后会狂暴

【修正指令】
返回 JSON：{"player_damage": <int>, "narrative": "<string>"}
```

**注意：**
- 只传**当前使用武器**的 special_rules，不是全部携带武器
- 护甲不传(固定规则结算)
- damage_multipliers 不传(固定规则结算)
- player_extra 仅在特殊规则相关时有效
- LLM 返回的 damage 经 `int()` 保护

### 敌人伤害修正 (`_llm_correct_enemy_round`)

与玩家修正独立，对每个有 `special_rules` 的敌人单独调用。Prompt 包含调查员背景、玩家 extra、敌人状态。修正后 `state.player_hp` 自动回退旧伤害+应用新伤害。

## 战斗叙事生成 (`_generate_combat_narrative`)

LLM flash 模型接收 `state.full_log`（所有攻防骰值记录）生成 ≤120 字战斗摘要。Prompt 和 response 自动保存到 `log_dir`。

CLI 战斗流程末尾调用，结果注入 `result["narrative"]` 追加到回合输出。LLM 不可用时 fallback 简单标签（"你战胜了敌人。" 等）。

## Boss 系统

### Boss Manager 架构

```
BossManager
 ├─ boss_encounters[]     ← L2 JSON
 │   ├─ engage_type: "at"          → 场景局部 | requirement 满足即触发
 │   ├─ engage_type: "interaction" → 场景局部 | requirement AND trigger(LLM)
 │   └─ engage_type: "event"       → 全局检测 | 每轮检查
 │
 ├─ _check_boss_requirements()
 │   ├─ hard_part(before ||)  → parse_hard_requirement(确定)
 │   └─ soft_part(after ||)   → _evaluate_boss_soft_condition(LLM)
 │
 ├─ build_combat_init()  → 从 BossLibrary 构建 CombatInit
 └─ resolve_outcome()    → 战斗后 Boss 状态管理
```

`||` 是 **AND** 分隔符，硬条件和软条件必须同时满足。

### Boss 与普通敌人合并

若同一回合同时触发普通战斗和 Boss 遭遇，Boss 敌人被合并到已有 CombatInit：

```python
if boss_combat_init:
    boss_enemy = boss_combat_init.enemies[0]
    if combat_init_result:
        combat_init_result.enemies.append(boss_enemy)    # 合并不覆盖
        self.world.enemies.register(boss_enemy)          # 注册到 EnemyManager
        self.world.enemies.add_to_combat(boss_enemy.instance_id)
    else:
        combat_init_result = boss_combat_init            # 纯 Boss 战
```

### 软条件 LLM 评估

输入：当前场景 + Boss名 + 玩家最近行动 + 触发条件文本
输出：`{"triggered": true/false, "reason": "..."}`
LLM 不可用时 fallback 通过。

## 伤害结算链(确定性)

```
_roll_damage(damage_spec, STR, SIZ)
    ├─ dice_n × D dice_d   → Σ random(1, sides)
    ├─ + bonus             → 固定加值
    ├─ + DB                → calc_db(STR, SIZ)
    └─ max(0, total)

_apply_armor(damage, armor_str)
    └─ max(0, damage - armor_value)

_apply_damage_multiplier(damage, damage_type, multipliers)
    └─ int(damage × multiplier)
```

## 阶段系统(Phase)

```json
{
  "trigger": "hp_below_pct:0.5",
  "name": "狂暴",
  "overrides": {"multi_attack": 2},
  "description": "Boss受伤后陷入狂暴"
}
```

每轮结束后检查，触发后应用 overrides 修改敌人属性。

## World AT(世界初始化)

world 场景的 auto_triggers 不通过常规 `_current_node()` 执行。在 `init_game()` 中显式解析并执行：

- `@spawn_enemy(enemy_ref, scene, quantity)` → `world.enemies.spawn()`（**自动合并群组**）
- `@grant_weapon(weapon_ref, scene, quantity)` → `world.scene_weapons[scene].append()`

运行时会打印：
```
[World AT] spawned Clicker x2 in 5号车厢 (Clicker_bdef558a)
[World AT] granted 试作型湮灭者 x1 in 6号车厢
```

## 多目标战斗

武器 `multi_attack > 1` 时，每轮可为每次攻击选择不同目标：
```
第1击: 毛瑟C96 → Clicker  | D100=45 → 造成5点伤害
第2击: 毛瑟C96 → 深潜者   | D100=62 → 未能命中
```

`player_actions[]` 记录所有攻击，LLM prompt 中全部展示。

## 战斗入口(CLI)使用示例

```
> 往5号车厢走
⚔ 进入战斗！遭遇：Clicker(HP26, x2), 深潜者(HP13, x1)

── 第1轮 ──
HP:12/12  SAN:60
  Clicker_c0 HP:13/13
  Clicker_c1 HP:13/13
  深潜者_c0 HP:13/13
动作: a)攻击 d)回避 f)逃跑 c)隐蔽 m)瞄准 g)蓄力
> a
武器: 1)拳击 2)踢击 3)试作型湮灭者
> 3
目标: 1)Clicker_c0 2)Clicker_c1 3)深潜者_c0
> 1
额外描述（可选，如"攻击核心"，直接回车跳过）:
>
  ✓ 试作型湮灭者 D100=34 regular 造成100点伤害
  Clicker_c1用噬咬击中！D100=72 造成5点伤害
  ...

── 战斗结束 ──
结果: ✅ 胜利 | HP:7 轮次:3
  📜 调查员以一击致命秒杀一只Clicker，随后与另一只交手两轮后将其击毙，深潜者伺机偷袭未遂。

💀 你被击败了…游戏结束。   ← 仅普通敌人 loss
```

## JSON 配置→运行时的字段传播注意事项

修改 JSON 库字段后必须逐层检查：

1. Library dataclass (`from_dict`/`to_dict`)
2. 运行时桥接对象 (`Weapon`、`EnemyInstance`)
3. 桥接代码 (`spawn()`〔含群组合并〕、拾取代码、`build_combat_init()`)
4. 消费端 (`_any_special_rules`、`_get_player_actions`、`_roll_damage`、`_init_combat`〔数量展开〕)

缺失任一层都会导致静默失效。使用 `_wattr()` 辅助函数统一 dict/dataclass 访问。
