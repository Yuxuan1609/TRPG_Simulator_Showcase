# Combat System 战斗系统详解

> `src/game/combat.py` — COC 7th 回合制独立战斗引擎

---

## 概述

CombatSystem 独立于 Keeper 管线运作。接收 `CombatInit`，执行回合制战斗循环，返回 `CombatResult`。不依赖 LLM，所有判定均为确定性 D100 掷骰。

### 数据流

```
Keeper.process_turn() 产出 CombatInit
        │
        ▼
CombatSystem.run_combat(CombatInit)
        │
        ├── _init_combat()       构建 CombatState，按 DEX 降序排列先攻
        │
        └── while not finished:
              _process_round(state, player, action, target)
                │
                ├── for actor in initiative_order:
                │     ├── player → _resolve_player_action()
                │     │              ├── 攻击 (punch/kick/weapon)
                │     │              ├── 回避 (dodge)
                │     │              └── 逃跑 (flee)
                │     └── enemy  → _resolve_enemy_action()
                │                  └── 攻击 (weight 加权随机)
                │
                └── 检查结束条件 → state.finished
        │
        ▼
CombatResult { outcome, defeated_instance_ids, player_hp, rounds, narrative }
```

---

## 先攻 (Initiative)

```python
_init_combat():
    order = [ (player, player.DEX), (enemy1, enemy1.DEX), ... ]
    order.sort(key=lambda x: -x[1])   # DEX 降序
    state.initiative_order = [oid for oid, _ in order]
```

DEX 最高的先行动。每轮按此固定顺序遍历一次。

**示例：**

| 先攻顺序 | DEX | 
|----------|-----|
| 深潜者 | 65 |
| player | 50 |
| Clicker | 50 |

→ 深潜者最先攻击，player 第二，Clicker 第三。

---

## 玩家动作

### 动作列表

| id | 标签 | 技能 | 伤害 | 说明 |
|----|------|------|------|------|
| `punch` | 拳击 | 格斗(拳) | 1D3+DB | 固定动作 |
| `kick` | 踢击 | 格斗(脚) | 1D6+DB | 固定动作 |
| `dodge` | 回避 | 回避 | — | 见下方 |
| `flee` | 逃跑 | DEX 对抗 | — | 见下方 |
| `weapon:<name>` | <武器名> | 武器关联技能 | 武器公式 | 从 Investigator.weapons 读取 |

技能值查找：`player.get_skill(name)` → 未掌握则 fallback 到 `STR//2`（攻击）或 `DEX//2`（回避）。

### 攻击动作

```
D100 ≤ skill_value ?
├── 成功 → _roll_damage(公式) → _apply_armor(伤害, 护甲) → 敌人 HP -= final_damage
└── 失败 → 无事发生，输出 "未能命中目标"
```

**成功等级**（`_get_tier`）：
- `roll == 1` → extreme
- `roll ≤ skill/5` → extreme  
- `roll ≤ skill/2` → hard
- `roll ≤ skill` → regular

> 注意：当前成功等级仅记录在 CombatAction.tier 中，**不影响伤害计算**。

### 回避 (dodge)

回避**始终成功**，无 D100 检定。设置 `state._player_dodging = True`。

**回避机制**：`_player_dodging` 只挡住**紧随其后的第一个敌人攻击**。

```
_resolve_enemy_action():
    if state._player_dodging:
        action.success = False           ← 敌人攻击强制未命中
        state._player_dodging = False   ← 标记清除
        return
```

**多敌人场景**：

```
先攻: player(50) → Clicker(50) → 深潜者(45)
玩家选回避:
  Clicker 攻击 → 被闪开 (_dodging 清除)
  深潜者 攻击 → 正常命中 ⚠
```

> 回避相当于"用一次先攻机会换一次免伤"。

### 逃跑 (flee)

```
D100 roll
成功条件: roll ≤ player.DEX  AND  roll < max(all_enemies_DEX)
```

| 场景 | 成功 range | 概率 |
|------|-----------|------|
| player DEX=50, enemy DEX=50 | 1~49 | ~49% |
| player DEX=50, enemy DEX=80 | 1~50 | ~50% |
| player DEX=50, enemy DEX=30 | 1~29 | ~29% |

**成功** → `state.finished = True`，`CombatResult.outcome = "win"`（无论敌人是否活着）。

**失败** → 浪费一次先攻机会，敌人照常攻击。

---

## 敌人动作

### 攻击选择

```python
attacks = enemy.attacks   # 从 LibraryEnemy 继承
weights = [a.weight for a in attacks]
return random.choices(attacks, weights=weights, k=1)[0]
```

### 命中检定

```python
enemy_skill = (DEX + POW) // 2     # 默认 50 + 50 → 50
action.success = D100_roll ≤ enemy_skill
```

### 伤害

命中后: `_roll_damage(attack.damage, enemy.STR, enemy.SIZ)` → 直接扣玩家 HP。

> **注意**：玩家无护甲。敌人攻击不经过 `_apply_armor`。

### Boss 路径

`_resolve_boss_action_stub()` — 当 enemy.flags 含 `"boss"` 时走此路径。当前行为与普通敌人相同，预留 LLM 扩展点。

---

## 伤害计算链

```
"1D6+DB"
  │
  ├── 解析 "1D6" → random(1, 6)
  ├── 解析 "DB"  → calc_db(STR, SIZ) → +1D4, -1, 0, +1D6 等
  └── 求和
  │
  ▼
_apply_armor(damage, "2点厚皮")
  │
  └── 提取数字 "2" → damage - 2 → max(0, result)
  │
  ▼
final_damage ≥ 0
```

`calc_db()` 对应 COC 7th 伤害加值表：

| STR+SIZ | DB | BUILD |
|---------|-----|-------|
| 2~64 | -2 | -2 |
| 65~84 | -1 | -1 |
| 85~124 | 0 | 0 |
| 125~164 | +1D4 | 1 |
| 165~204 | +1D6 | 2 |

---

## 每轮执行顺序 (process_round)

```
state.log = []               ← 清空上轮日志
state._player_dodging = False

for actor in initiative_order:
    if actor == "player":
        action = _resolve_player_action(...)
        state.log.append(action)
        if state.finished: return    ← 逃跑成功 / 玩家死亡
    else:
        if enemy 活着:
            action = _resolve_enemy_action(...)
            state.log.append(action)
            if player_hp ≤ 0:
                state.finished = True
                return

if 所有敌人 HP ≤ 0:
    state.finished = True

state.round += 1
```

---

## run_combat() 入口

```python
def run_combat(combat_init):
    state = _init_combat(combat_init)
    while not state.finished:
        target = 第一个活着的敌人
        _process_round(state, player, "punch", target)   # ← 固定拳击！
```

> **当前限制**：`run_combat()` 硬编码 `"punch"` 动作（`combat.py:124`）。交互式控制需外部逐轮调用 `_process_round()` 并传入选择的 action_id。

---

## 输出

```python
CombatResult(
    outcome="win" | "loss",         # player_hp > 0 且 敌全灭 → win
    defeated_instance_ids=[...],
    player_hp=剩余HP,
    player_san=当前SAN（战斗中不变）,
    rounds=经过轮数,
    narrative=""                    # O9: LLM 增强后填充
)
```

---

## LLM 增强 (O9 — 未实现)

- `CombatSystem.__init__` 接收 `llm_enhancement: bool` 参数，默认读取 `config.py` 的 `COMBAT_LLM_ENHANCEMENT`（当前 `False`）
- `_generate_combat_narrative()` 占位方法
- 开启后：每轮战斗 → `build_combat_narrative_prompt()` → LLM 生成每轮叙事；战斗结束 → 汇总 → 填入 `CombatResult.narrative`
- 战斗输出走独立管线，不经过 Narrator

---

## 测试

| 文件 | 说明 |
|------|------|
| `tests/test_combat.py` | 10 case 单元测试（伤害/护甲/等级/状态） |
| `tests/test_combat_harness.py` | 完整 CombatSystem 集成测试 |
| `tests/test_combat_interactive.py` | **交互式** CombatInit → CombatResult 接入测试 |
