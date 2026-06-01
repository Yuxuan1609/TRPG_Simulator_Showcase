# 战斗系统分层重构设计

> 2026-05-28 | 状态：已确认

## 一、目标

将当前纯确定性的回合制战斗引擎升级为**分层架构**：确定性执行 + LLM 可选修正层。支持武器/敌人/Boss 的结构化特殊规则和自由文本 `special_rules`，同时保持 `CombatInit` / `CombatResult` 接口兼容。

## 二、玩家输入模型

### 输入格式

每轮玩家输入是三段式：

```
选择武器 → 选 N 次目标（N = weapon.multi_attack）→ [额外描述（选填）]
```

- **武器选择**：可用动作列表（`拳击` `踢击` `武器:xxx` `回避` `逃跑` `隐蔽` `瞄准` `蓄力`），玩家从中选一个 action_id
- **目标选择**：根据 `multi_attack` 值选 N 次，每次从存活敌人列表中选。同一目标多选 = 连续攻击同一目标
- **额外描述**：自由文本，可选（如 `"瞄准核心"`）。空则跳过 LLM 修正层
- **Fallback**：空输入 = 重复上轮动作 + 目标

### 前端/CLI 支持

后端暴露可用动作列表 + 存活敌人列表供前端渲染选择器。额外描述为文本输入框。

## 三、结构化特殊规则模板

### Weapon 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `damage_type` | `str` | `"物理"` | `"穿刺"` / `"火焰"` / `"精神"` / ... |
| `armor_piercing` | `int` | `0` | 穿透护甲值 |
| `attack_bonus` | `int` | `0` | 命中 D100 修正 |
| `multi_attack` | `int` | `1` | 每轮可攻击次数 |
| `special_rules` | `str` | `""` | 自由文本，非结构化规则 |

### Enemy（普通）新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `multi_attack` | `int` | `1` | 每轮攻击次数 |
| `damage_multipliers` | `dict[str, float]` | `{}` | 伤害倍率：`>1.0`=易伤，`<1.0`=抗性，`0`=免疫，`1.0`=正常（可省略） |
| `dodge_bonus` | `int` | `0` | 闪避 D100 修正 |
| `special_rules` | `str` | `""` | 自由文本 |

### Boss 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `multi_attack` | `int` | `1` | 同上 |
| `damage_multipliers` | `dict[str, float]` | `{}` | 同上 |
| `dodge_bonus` | `int` | `0` | 同上 |
| `phases` | `list[Phase]` | `[]` | 阶段定义 |
| `special_rules` | `str` | `""` | 自由文本，含 Boss AI 决策规则 |

### Phase 子结构

```python
@dataclass
class Phase:
    trigger: str         # "hp_below_pct:0.5" 或 "round:3"
    name: str            # "二阶段：核心暴露"
    overrides: dict      # {field: new_value}，覆盖 multi_attack/damage_multipliers/等
    description: str     # 人类可读，"触手断裂，核心暴露在空气中"
```

## 四、战斗引擎执行流程

### 整体流程图

```
玩家选择动作 + 目标(N次) + [额外描述]
          │
          ▼
┌──────────────────────────────────────────────────┐
│  1. 确定性执行层                                  │
│     ├─ 解析结构化特殊规则（multi_attack /        │
│     │   resistances / armor_piercing / 等）       │
│     ├─ 掷骰 + 伤害计算 + 命中判定                │
│     ├─ 敌人 AI：从可用攻击中随机选用              │
│     ├─ Boss 优先使用 special_rules AI，否则随机   │
│     └─ 产出 RoundResult（暂不生效）               │
├──────────────────────────────────────────────────┤
│  2. LLM 修正层（Gate 触发）                       │
│     触发条件：                                    │
│     (weapon.special_rules | boss.special_rules    │
│                        | enemy.special_rules) != ""│
│     ├─ 输入：RoundResult + 所有 special_rules     │
│     │         + 额外描述 + 当前战场快照            │
│     ├─ LLM 输出：同结构的 RoundResult（改字段值）  │
│     └─ 无 spec_rules → 跳过，直接用确定性结果     │
├──────────────────────────────────────────────────┤
│  3. 结果生效                                     │
│     ├─ 应用（修正后的）RoundResult               │
│     ├─ 更新 HP / status / phase                  │
│     └─ 判定存活 / 胜利 / 失败                     │
└──────────────────────────────────────────────────┘
```

### 关键原则

- **LLM 是参数修正器**：只能改 RoundResult 字段的值（抗性倍率、伤害倍率、目标映射、附加效果等），不能改写判决逻辑
- **Gate 机制**：无 `special_rules` 时 LLM 层完全不调用，性能等同当前系统
- **结构一致**：确定性层和 LLM 层输出完全同结构的 `RoundResult`

## 五、核心数据结构

### RoundResult

```python
@dataclass
class RoundResult:
    round: int
    player_action: str           # "拳击" / "踢击" / "武器:xxx" / "回避" / etc.
    player_target: str           # enemy instance_id
    player_roll: int             # D100
    player_tier: str             # fumble | failure | regular | hard | extreme
    player_damage: int           # 0 if miss/dodge
    player_damage_type: str      # "物理" / "穿刺" / etc.
    player_effects: list[str]    # ["击退", "中毒1D3/轮"]

    enemy_actions: list[dict]    # [{enemy_id, action, roll, tier, damage, damage_type, effects}]

    status_changes: list[dict]   # [{entity_id, field, old, new}] 如 HP/phase/status

    narrative: str               # 人类可读的轮次摘要
```

### CombatInit（增量扩展）

```python
@dataclass
class CombatInit:
    enemies: list[Any] = []                # 不变
    player: Any = None                     # 不变
    scene: str = ""                        # 不变
    initiative_context: str = ""           # 不变
    environment_actions: list[dict] = []   # 不变
    # ── 新增 ──
    player_action: str = ""                # action_id
    player_targets: list[str] = []         # 多目标支持
    player_extra: str = ""                 # 额外描述（可选）
```

### CombatResult（增量扩展）

```python
@dataclass
class CombatResult:
    outcome: str = ""                                 # 不变
    defeated_instance_ids: list[str] = []             # 不变
    narrative: str = ""                               # 不变
    player_hp: int = 0                                # 不变
    player_san: int = 0                               # 不变
    rounds: int = 0                                   # 不变
    # ── 新增 ──
    round_log: list[RoundResult] = []                 # 每轮详细日志
```

## 六、接口兼容性

| 接口 | 变更类型 | 说明 |
|------|----------|------|
| `CombatInit` | **新增字段** | 新增 3 个可选字段，默认值保证向后兼容 |
| `CombatResult` | **新增字段** | 新增 `round_log`，默认空列表 |
| `CombatSystem.run_combat()` | **签名扩展** | 已有 `player_action` 参数，`player_targets` 和 `player_extra` 通过 `CombatInit` 传入 |
| `game_loop.run_turn()` | **无变更** | 后处理分流逻辑不变 |
| `EnemyManager` | **无变更** | `enter_combat` / `exit_combat` 接口不变 |
| `BossManager` | **增量扩展** | `Phase` 解析 + `special_rules` 注入 |

## 七、JSON 数据格式变更

武器/敌人/Boss 库的 JSON 文件需要新增上述结构化字段。`special_rules` 和 `phases` 由模组作者/KP 填写。

```jsonc
// 武器示例
{
  "name": "火焰喷射器",
  "damage": "2D6",
  "damage_type": "火焰",
  "armor_piercing": 0,
  "attack_bonus": 0,
  "multi_attack": 1,
  "special_rules": "对植物类敌人伤害加倍；雨天使用时需检定 DEX 避免炸膛"
}

// Boss 示例
{
  "boss_ref": "深潜者祭司",
  "multi_attack": 2,
  "damage_multipliers": {"穿刺": 0.5, "火焰": 0.25, "钝击": 1.5},
  "phases": [
    {
      "trigger": "hp_below_pct:0.5",
      "name": "二阶段：狂怒",
      "overrides": {"multi_attack": 3, "dodge_bonus": 10},
      "description": "祭司陷入狂怒，攻击次数增加但防御下降"
    }
  ],
  "special_rules": "二阶段后优先攻击最近的目标；每 3 轮释放一次心灵冲击（SAN 检定 1D3/1D6）"
}
```

## 八、LLM 修正层 Prompt 概要

```
系统提示：你是 COC 7th 战斗裁判助理。根据 special_rules 修正 RoundResult 的字段值。
你只能修改参数值（抗性、伤害倍率、目标映射、状态变更、叙事文本），不能改变判决逻辑。

输入：
- RoundResult（确定性层输出）
- weapon.special_rules
- boss.special_rules
- enemy.special_rules
- 玩家额外描述
- 战场快照（由 _build_battle_snapshot() 辅助函数生成）

输出：同结构的 RoundResult JSON
```

LLM 模型：flash 模型（`LLM_FLASH_MODEL`），`json_mode=True`，fallback 到确定性原值。

### _build_battle_snapshot() 辅助函数

每轮调用，生成 LLM 所需的战场上下文字符串（不含 D100 掷骰值，掷骰已含在 RoundResult 中）：

```python
def _build_battle_snapshot(state: CombatState, player, boss_phase: str = "") -> str:
    """返回 ≤500 字符的战场快照，含轮数、HP、阶段、实体状态。"""
    lines = [
        f"第{state.round}轮",
        f"调查员 HP:{state.player_hp}/{state.player_hp_max} SAN:{state.player_san}",
    ]
    if boss_phase:
        lines.append(f"Boss当前阶段:{boss_phase}")
    for e in state.enemies:
        hp_pct = f"{getattr(e, 'hp', 0)}/{getattr(e, 'hp_max', getattr(e, 'hp', 0))}"
        phase = getattr(e, '_current_phase', '')
        phase_str = f" 阶段:{phase}" if phase else ""
        lines.append(f"[{e.instance_id}] {e.enemy_ref} HP:{hp_pct} status:{getattr(e, 'status', '?')}{phase_str}")
    return "\n".join(lines)
```

## 九、待后续

- 法术系统接入：`special_rules` 字段已预留，法术体系实现后直接复用本层的 LLM 修正机制
- 前端改造：动作选择器 + 目标多选控件 + 额外描述输入框
- 战斗 AI 单独议题：当前仅随机选用攻击 + special_rules 文本描述。若后续需要更复杂的通用 AI，另开设计
