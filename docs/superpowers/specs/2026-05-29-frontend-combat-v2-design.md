# 前端交互式战斗系统 v2 设计文档

> 日期: 2026-05-29
> 对应后端: `docs/combat-system-v2.md`

## 目标

将 CLI `run_game.py` 中的交互式逐轮战斗（`_run_interactive_combat`）完整接入前端，用按钮/选项卡替代纯文本输入。战斗进行时左侧面板（场景卡）切换为"战斗态势面板"。

## 架构决策

**方案 A：前端状态机 + 后端单轮 API**

- 前端自主驱动战斗交互流程
- 每轮玩家选完动作 → 发 `/api/combat/round` → 后端执行单轮 → 返回新状态
- 前后端解耦，状态由前端维护，避免后端 session 管理复杂度

## 数据流

```
玩家输入行动 → keeper.process_turn() → 返回 combat_init
  ↓
前端检测到 combat_init，左侧场景卡切换为"战斗面板"
  ↓
[战斗轮循环]
  前端显示：玩家HP/SAN | 敌人列表(HP条) | 动作按钮
  玩家点击：动作 → (如需)选武器 → (如需)选目标 → 填写额外意图 → 点击"执行"
  前端 POST /api/combat/round {action_id, target_ids, player_extra, current_state}
  后端重建 CombatState → 执行单轮 → _llm_correct_round → 返回新状态
  前端更新：左侧日志区追加本轮结果 | 敌人HP条刷新 | 玩家HP/SAN刷新
  ↓
finished=true → 左侧面板切回场景卡 | 中间叙事区插入战斗总结 | 右侧角色卡同步
```

## 左侧面板布局（战斗态）

```
┌─────────────────────────────────┐
│ ⚔ 战斗 — 5号车厢        [↕折叠] │  ← 标题栏，可折叠/展开
├─────────────────────────────────┤
│ 调查员 张弛                      │
│ HP ████████░░ 8/12              │  ← 玩家实时状态条
│ SAN █████████░ 55/60            │
├─────────────────────────────────┤
│ 敌人                            │
│ Clicker_c0  HP ██████░░░ 6/10  │  ← 每个敌人一行，带 HP 条
│ Clicker_c1  HP █████████ 10/10 │
│ 深潜者_c0   HP ████░░░░░ 4/10  │
├─────────────────────────────────┤
│ [攻击] [回避] [逃跑]            │  ← 动作按钮行
│ [隐蔽] [瞄准] [蓄力]            │
├─────────────────────────────────┤
│ 武器: [试作型湮灭者 ▼]          │  ← 点击"攻击"后展开武器下拉
│ 目标: [c0 ×1] [c1] [c1]        │  ← 目标可重复选择（multi_attack）
├─────────────────────────────────┤
│ 额外意图（可选）                 │
│ [________________]              │  ← 常驻文本框
├─────────────────────────────────┤
│ [执行回合]                      │  ← 主按钮
├─────────────────────────────────┤
│ ── 战斗日志 ──                  │
│ [R1] 试作型湮灭者 D100=34 命中  │
│      造成100伤害 → Clicker_c0    │
│ [R1] Clicker_c1 噬咬 D100=72   │
│      未命中                      │
└─────────────────────────────────┘
```

### 交互规则

| 交互 | 行为 |
|------|------|
| 点击非攻击动作（回避/逃跑/隐蔽/瞄准/蓄力） | 直接解锁"执行回合"，无需选武器/目标 |
| 点击"攻击" | 展开武器下拉（从 `combat_init.player.weapons` 生成），默认选中第一个；同时显示目标选择按钮 |
| 目标选择（支持 multi_attack） | 敌人 HP>0 的显示为可点击按钮；点击一次选中（显示 ×1），再次点击同一目标增加次数（×2, ×3...），总数不超过 `multi_attack`；点击其他目标分配剩余次数 |
| 执行回合 | 发送 `/api/combat/round`，按钮 loading 态防重复点击 |
| 回合结果 | 日志区 append 本轮结果；敌人/玩家 HP 条动画更新；若 `finished=true` 进入结束流程 |
| 逃跑 | 点击"逃跑"按钮 → 发送 `action_id="flee"` → 后端 DEX 判定 → 成功则 `finished=true, outcome="flee"`；**逃跑 ≠ 关闭面板**，逃跑失败继续战斗 |
| 折叠面板 | 标题栏的 `[↕折叠]` 按钮可最小化左侧面板，但战斗仍在进行；展开后恢复显示 |

## 后端 API

### `POST /api/combat/round`

**请求：**
```json
{
  "combat_init": { ...CombatInit serialized... },
  "current_state": {
    "round": 1,
    "player_hp": 10,
    "player_hp_max": 12,
    "player_san": 60,
    "enemies": [
      {"instance_id": "Clicker_c0", "enemy_ref": "Clicker", "hp": 10, "hp_max": 10, "quantity": 1, ...}
    ],
    "full_log": [...],
    "initiative_order": ["player", "Clicker_c0", "Clicker_c1"]
  },
  "action_id": "weapon:试作型湮灭者",
  "target_ids": ["Clicker_c0"],
  "player_extra": "攻击核心"
}
```

**响应：**
```json
{
  "finished": false,
  "outcome": null,
  "player_hp": 8,
  "player_hp_max": 12,
  "player_san": 55,
  "enemies": [
    {"instance_id": "Clicker_c0", "enemy_ref": "Clicker", "hp": 0, "hp_max": 10, "status": "defeated"}
  ],
  "round_log": [
    {"actor": "player", "action_type": "attack", "weapon": "试作型湮灭者", "roll": 34, "tier": "regular", "damage": 100, "target": "Clicker_c0", "success": true, "damage_type": "物理"},
    {"actor": "Clicker_c1", "action_type": "attack", "weapon": "噬咬", "roll": 72, "tier": "failure", "damage": 0, "target": "player", "success": false}
  ],
  "round_narrative": "你举起试作型裁决者，一击将Clicker_c0打得粉碎...",
  "is_boss": false,
  "game_over": false,
  "round": 2
}
```

### 实现要点

后端需要新增 `run_single_round()` 方法：
1. 从请求中的 `current_state` + `combat_init` 重建 `CombatState`
2. 调用 `_resolve_player_action()` + `_resolve_enemy_action()`
3. 执行 `_llm_correct_round()`（如有特殊规则）和 `_llm_correct_enemy_round()`
4. 结算伤害到敌人 HP 和玩家 HP
5. 检查结束条件（玩家 HP≤0 / 敌人全灭 / 逃跑成功 / 回合超限）
6. 返回新的 `current_state` 给前端

**注意**：重建 `CombatState` 时不能重新调用 `_init_combat()`（那会重置敌人 HP 和展开 quantity），而是直接用传入的 `current_state.enemies` 和 HP 值。

## 前端状态机

```javascript
combatState = {
  active: false,
  combatInit: null,          // 从 turn 响应获得
  round: 1,
  playerHp: 0,
  playerHpMax: 0,
  playerSan: 0,
  enemies: [],               // 当前活着的敌人列表
  fullLog: [],               // 传给后端用于 LLM 修正
  initiativeOrder: [],
  selectedAction: null,      // "attack" | "dodge" | "flee" | "conceal" | "aim" | "charge"
  selectedWeapon: null,      // weapon action id
  targetCounts: {},          // { "Clicker_c0": 2, "Clicker_c1": 1 }
  playerExtra: "",
  finished: false,
  outcome: null,             // "win" | "loss" | "flee" | "draw"
  isBoss: false,
  gameOver: false,
  narrative: ""              // LLM 生成的战斗摘要
};
```

## 战斗结束流程

1. 前端收到 `finished=true`
2. `combatState.active = false`
3. 左侧面板自动切回场景卡
4. 中间叙事区插入战斗总结：`combat.narrative`
5. 右侧角色卡刷新（同步最终 HP/SAN）
6. 如果 `game_over=true`：显示结局，锁定输入

## 与现有 `/api/game/turn` 的衔接

当前 `game.py` 第241-274行在收到 `combat_init` 时会自动执行 `CombatSystem.run_combat()`（自动战斗）。接入本系统后：

- 后端 `/api/game/turn` 不再自动执行战斗
- 当 `turn` 响应包含 `combat_init` 且 **无** `combat`（即尚未执行）时，前端进入战斗模式
- 战斗结束后，前端不再向 `/api/game/turn` 发请求，而是等待玩家输入正常行动

## 失败与错误处理

| 场景 | 处理 |
|------|------|
| 后端 API 500 | 左侧面板日志区显示"回合执行错误"，解锁按钮允许重试 |
| 网络断开 | 显示重试按钮，保留当前选择状态 |
| 战斗中页面刷新 | 刷新后从 `/api/game/state` 恢复，若检测到 `combat_init` 存在但未结束，可提示"战斗状态已丢失，请继续正常回合" |

## 文件变更清单

| 文件 | 变更 |
|------|------|
| `frontend/templates/game.html` | 新增战斗面板 HTML + JavaScript 状态机 |
| `frontend/routers/game.py` | 新增 `POST /api/combat/round`；修改 `/api/game/turn` 去掉自动战斗逻辑 |
| `src/game/combat.py` | 新增 `run_single_round()` 方法，支持从序列化状态重建并执行单轮 |

## 待升级（本版本不做）

- 战斗面板折叠/展开动画优化
- 战斗中页面刷新后的状态恢复（持久化 combat session）
- 战斗特效/动画（HP 条变色、伤害数字飘字）
