# ═══════════════════════════════════════════════════════════════
#  TRPG 调查员助手 —— 主流程 (Multi-Agent 架构, CLI 纯文本)
#  ═══════════════════════════════════════════════════════════════
#  运行: python run_game.py
#  依赖: pip install openai

import sys
import json
import os as _os
from datetime import datetime

sys.path.insert(0, "src")

from game_loop import init_game, run_turn, setup_logging

_log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
_log_dir = setup_logging()

# ═══════════════════════════════════════════════════════════════
#  武器/敌人库初始化
# ═══════════════════════════════════════════════════════════════

weapon_lib = WeaponLibrary()
weapon_lib.load_core()
enemy_lib = EnemyLibrary()
enemy_lib.load_core()
injector = ContentInjector(weapon_lib, enemy_lib)
print(f"[info] 武器库：{len(weapon_lib)} 件 | 敌人库：{len(enemy_lib)} 个 | "
      f"注入器：{'就绪' if injector else '未初始化'}")

# ═══════════════════════════════════════════════════════════════
#  游戏主循环
# ═══════════════════════════════════════════════════════════════

def run_game(character_path: str = None):
    game = init_game(
        l2_path="data/modules/测试模组0528v2/l2_keeper_test.json",
        l1_path="data/modules/测试模组0528v2/l1_player.json",
        l3_path="data/modules/测试模组0528v2/l3_designer.json",
        start_node="6号车厢",
    )

    keeper = game["keeper"]
    world = keeper.world
    print(f"场景数：{len(world.graph.nodes)}, 事件数：{len(world.graph.events)}")

    # 加载调查员
    if character_path is None:
        character_path = "investigator/test_character.json"

    if _os.path.exists(character_path):
        investigator = load_investigator(character_path)
        print(f"[info] 已加载调查员：{investigator.name} | "
              f"职业：{investigator.occupation.name if investigator.occupation else '无'} | "
              f"HP={investigator.derived.HP} SAN={investigator.derived.SAN}")
    else:
        print(f"[warn] 未找到角色卡 {character_path}，掷骰生成默认调查员...")
        investigator = Investigator(name="调查员A", age=25, gender="男")
        investigator.stats = roll_stats()
        investigator.skills = create_skill_list()
        investigator.derived = calc_derived(investigator.stats, investigator.age)
        print(f"[info] 已生成调查员：{investigator.name} | "
              f"HP={investigator.derived.HP} SAN={investigator.derived.SAN}")

    world.set_player(investigator)
    # 应用 AT_WORLD 中延后的 item_gain（init_game 时 player 尚未设置）
    for item_gain in game.get("pending_world_items", []):
        if hasattr(investigator, 'item_manager'):
            investigator.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)
            print(f"[World AT] gained item {item_gain.item_name} x{item_gain.quantity}")
    _os.makedirs("data/saves", exist_ok=True)

    print("[info] 游戏开始。输入 /help 查看可用命令。")
    print(f"\n── 当前场景 ──")
    print(_scene_text(world))

    # 开场
    initial = run_turn(game, "（游戏开始）")
    ts = initial.get("timestamp", "")
    if ts:
        print(f"[{ts}]")
    _print_turn_output(initial.get("player_snapshot"), initial["brief"], initial["narrative"])

    # 主循环
    while True:
        try:
            cmd = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[info] 游戏结束。")
            break
        if not cmd:
            continue

        if cmd in ("exit", "quit", "/quit", "/exit"):
            print("[info] 游戏结束。")
            break
        elif cmd.startswith("/scene"):
            print(_scene_text(world))
            continue
        elif cmd.startswith("/info"):
            print(json.dumps(world.get_scene_info(), ensure_ascii=False, indent=2))
            continue
        elif cmd.startswith("/events"):
            active = world.get_active_event_effects()
            if active:
                for name, impact in active:
                    print(f"◆ {name}\n  {impact}")
            else:
                print("（无已触发事件）")
            continue
        elif cmd.startswith("/flags"):
            rs = world.runtime_state
            if rs:
                items = []
                for eid, s in rs.items():
                    if s.completed:
                        items.append(f"{eid}: {'✓' if s.completed else '✗'} tier={s.result_tier or '-'} retries={s.retries}")
                print("已完成实体：\n" + "\n".join(items) if items else "（无）")
            else:
                print("（无运行时状态）")
            continue
        elif cmd.startswith("/char"):
            if world.player:
                print(str(world.player))
            else:
                print("[warn] （未设置调查员）")
            continue
        elif cmd.startswith("/save"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            world.save_state(path)
            print(f"[info] 存档已保存至 {path}")
            continue
        elif cmd.startswith("/load"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            if _os.path.exists(path):
                from scenario_core import ScenarioWorld
                new_world = ScenarioWorld.load_state(path)
                keeper.world = new_world
                world = new_world
                print(f"[info] 已从 {path} 读档")
                print(_scene_text(world))
            else:
                print(f"[warn] 存档 {path} 不存在")
            continue
        elif cmd.startswith("/help"):
            print(
                "/scene 场景 | /info 状态 | /events 事件 | /flags 运行时状态\n"
                "/char 角色 | /trigger <E1> | /spawn enemy/weapon <名称>\n"
                "/save <槽位> | /load <槽位> | exit"
            )
            continue

        # 正常回合
        result = run_turn(game, cmd)

        # 战斗：进入交互式子循环
        combat_init = result.get("combat_init")
        if combat_init and combat_init.enemies:
            combat_result = _run_interactive_combat(game, combat_init)
            result["combat"] = combat_result
            if combat_result and combat_result.get("outcome"):
                narrative_text = combat_result.get("narrative", "")
                outcome = combat_result.get("outcome", "?")
                labels = {"win": "你战胜了敌人。", "loss": "你被击败了…", "draw": "战斗陷入僵局。", "flee": "你成功逃离了战斗。"}
                summary = narrative_text or labels.get(outcome, f"战斗结束({outcome})。")
                result["narrative"] = (result.get("narrative", "") or "") + f"\n\n---\n⚔ {summary}"
                result["brief"] = (result.get("brief", "") or "") + f" [战斗: {outcome}]"
                # 被普通敌人击败 → 游戏结束
                if combat_result.get("game_over"):
                    result["game_over"] = True
                    print(f"\n💀 你被击败了…游戏结束。")
                    break

        ending = result.get("ending")
        if ending:
            print(f"\n【结局触发】{ending['name']}：{ending['narrative']}")

        ts = result.get("timestamp", "")
        if ts:
            print(f"[{ts}]")

        _print_turn_output(result.get("player_snapshot"), result["brief"], result["narrative"])

        if ending:
            print("[info] 游戏结束。")
            break


def _build_scene_snapshot(world) -> dict | None:
    """从 world 构建 PlayerFacingSnapshot 格式的 dict。"""
    node = world.graph.nodes.get(world.current_location)
    if not node:
        return None
    return {
        "scene_name": world.current_location,
        "scene_description": node.description or "",
        "exits": [{"target": e.target, "method": e.method} for e in node.edges],
        "time": world.clock.to_dict(),
        "npcs": world.npcs.get_in_scene_snapshot(world.current_location) if world.npcs else [],
        "enemies": world.enemies.get_active_in_scene_snapshot(world.current_location) if world.enemies else [],
        "combat": None,
        "skill_checks": [],
    }


def _scene_text(world):
    """构建 Markdown 场景状态（/scene 命令用）。"""
    snap = _build_scene_snapshot(world)
    if not snap:
        return "（未知场景）"
    return _format_snapshot_chapters(snap)

def _g(obj, key, default=None):
    """Safe getter that works for both dicts and dataclass objects."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _format_snapshot_chapters(snap) -> str:
    """将 PlayerFacingSnapshot 格式化为半结构化 Markdown。
    
    输出示例:
    ## 场景
    6号车厢。车厢内弥漫着陈旧的气味...可以通往 7号车厢（向东走）。
    
    ## 角色
    京山人吉——瘦高男子，神色警惕。
    
    ## 时间
    第1天，夜间 04:30。
    
    ## 技能
    I1: 侦查检定 → 常规成功 (D100=45/50)
    """
    chapters = []
    
    # Scene
    name = _g(snap, "scene_name", "")
    desc = _g(snap, "scene_description", "")
    exits = _g(snap, "exits", [])
    scene_prose = name or "未知"
    if desc:
        scene_prose += f"。{desc.strip().rstrip('。')}"
    if exits:
        exit_labels = [f"{e.get('target','?')}（{e.get('method','?')}）" for e in exits]
        scene_prose += f"。可以通往{'、'.join(exit_labels)}"
    scene_prose += "。"
    chapters.append(f"## 场景\n{scene_prose}")
    
    # NPCs
    npcs = _g(snap, "npcs", [])
    if npcs:
        npc_prose = "、".join(
            f"{_g(n, 'name', '?')}——{_g(n, 'brief', '')}{'，'+_g(n,'demeanor','') if _g(n,'demeanor') else ''}"
            for n in npcs
        )
        chapters.append(f"## 角色\n{npc_prose}。")

    # Enemies
    enemies_data = _g(snap, "enemies", [])
    if enemies_data:
        enemy_lines = []
        for e in enemies_data:
            ref = _g(e, "enemy_ref", "?")
            status = _g(e, "status", "?")
            qty = _g(e, "quantity", 1)
            enemy_lines.append(f"{ref}×{qty} [{status}]")
        chapters.append(f"## 敌人\n{'，'.join(enemy_lines)}")
    
    # Time — clock.to_dict() returns {"game_time": int, "time_context": str}
    t = _g(snap, "time", {})
    if t:
        parts = []
        gt = int(_g(t, "game_time", 0))
        day = gt // 1440 if gt else 0
        hour_val = (gt % 1440) // 60 if gt else 0
        min_val = gt % 60
        if day:
            parts.append(f"第{day}天")
        if hour_val < 5: tod = "夜间"
        elif hour_val < 8: tod = "早晨"
        elif hour_val < 17: tod = "白天"
        elif hour_val < 20: tod = "黄昏"
        else: tod = "夜间"
        parts.append(tod)
        parts.append(f"{int(hour_val):02d}:{int(min_val):02d}")
        if parts:
            chapters.append(f"## 时间\n{'，'.join(parts)}\u3002")
    
    # Combat
    combat = _g(snap, "combat")
    if combat:
        outcome = _g(combat, "outcome", "?")
        narrative = _g(combat, "narrative", "")
        chapters.append(f"## 战斗\n结果: {outcome}\u3002{narrative}")
    
    # Skills
    skill_checks = _g(snap, "skill_checks", [])
    if skill_checks:
        tier_labels = {"extreme": "极难成功", "hard": "困难成功", "regular": "常规成功",
                       "failure": "失败", "fumble": "大失败"}
        lines = []
        for sc in skill_checks:
            eid = _g(sc, "entity_id", "?")
            tier = _g(sc, "tier", "")
            tier_label = tier_labels.get(tier, tier or "?")
            raw = _g(sc, "raw_roll", 0)
            target = _g(sc, "target", 0)
            dice_str = f"（D100={raw}/{target}）" if raw else ""
            succ = "成功" if _g(sc, "success") else "失败"
            enh = _g(sc, "enhancement")
            enh_str = f"→特质增强为{_g(enh,'tier','')}" if enh and _g(enh, "tier") else ""
            lines.append(f"{eid}: {succ}，{tier_label}{dice_str}{'，'+enh_str if enh_str else ''}")
        chapters.append(f"## 技能\n" + "\n".join(lines))
    
    return "\n\n".join(chapters)

def _print_turn_output(snap, brief, narrative):
    """统一的回合输出：Narrator 叙事 + World Snapshot。"""
    output_parts = []
    
    if narrative:
        output_parts.append(f"## 叙事\n{narrative}")
    
    if snap:
        output_parts.append(_format_snapshot_chapters(snap))
    elif brief:
        output_parts.append(brief)
    
    print("\n\n" + "\n\n".join(output_parts))


def _run_interactive_combat(game, combat_init) -> dict | None:
    """交互式战斗子循环。返回 combat_data dict 或 None。"""
    from game.combat import CombatSystem
    from game_loop import run_turn

    world = game["keeper"].world
    cs = CombatSystem()
    state = cs._init_combat(combat_init)
    max_rounds = 20

    enemy_desc = ", ".join(
        f"{getattr(e, 'enemy_ref', '?')}(HP{getattr(e, 'hp', 0)})"
        for e in combat_init.enemies
    )
    print(f"\n⚔ 进入战斗！遭遇：{enemy_desc}")

    player = combat_init.player
    available = cs._get_player_actions(player)
    weapon_actions = [a for a in available if a["id"].startswith("weapon:")]

    while not state.finished and state.round <= max_rounds:
        alive = [e for e in state.enemies if getattr(e, 'hp', 1) > 0]
        if not alive:
            state.finished = True
            break

        print(f"\n── 第{state.round}轮 ──")
        print(f"HP:{state.player_hp}/{state.player_hp_max}  SAN:{state.player_san}")
        for e in state.enemies:
            hp, hpmax = getattr(e, 'hp', 0), getattr(e, 'hp_max', getattr(e, 'hp', 10))
            print(f"  {getattr(e, 'enemy_ref', '?')} HP:{hp}/{hpmax}")

        # 玩家选择
        action_id = "punch"
        target = alive[0].instance_id
        while True:
            print("\n动作: a)攻击 d)回避 f)逃跑 c)隐蔽 m)瞄准 g)蓄力")
            choice = input("> ").strip().lower()
            if choice == 'd':
                action_id = "dodge"; break
            elif choice == 'f':
                action_id = "flee"; break
            elif choice == 'c':
                action_id = "conceal"; break
            elif choice == 'm':
                action_id = "aim"; break
            elif choice == 'g':
                action_id = "charge"; break
            elif choice == 'a':
                # 武器选择
                if weapon_actions:
                    print("武器: " + ", ".join(
                        f"{i+1}){a['label']}" for i, a in enumerate(weapon_actions)))
                    wc = input("> ").strip()
                    if wc.isdigit() and 1 <= int(wc) <= len(weapon_actions):
                        action_id = weapon_actions[int(wc) - 1]["id"]
                # 多目标选择
                if len(alive) > 1:
                    print("目标: " + ", ".join(
                        f"{i+1}){getattr(e, 'enemy_ref', '?')}" for i, e in enumerate(alive)))
                    tc = input("> ").strip()
                    if tc.isdigit() and 1 <= int(tc) <= len(alive):
                        target = alive[int(tc) - 1].instance_id
                # 额外意图（可选，仅特殊规则时生效）
                player_extra = ""
                if weapon_actions:
                    print("额外描述（可选，如\"攻击核心\"，直接回车跳过）:")
                    player_extra = input("> ").strip()
                break
        # 执行一轮
        state.log = []
        state._player_dodging = False
        pa = cs._resolve_player_action(state, player, action_id, target)
        pa.round_num = state.round
        state.log.append(pa)
        state.full_log.append(pa)

        # 敌人行动
        for iid in state.initiative_order:
            if iid == "player":
                continue
            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'hp', 1) <= 0:
                continue
            ea = cs._resolve_enemy_action(state, enemy, player)
            ea.round_num = state.round
            state.log.append(ea)
            state.full_log.append(ea)

        # LLM 修正（特殊规则武器/敌人）
        needs_llm = cs._any_special_rules(combat_init, state.enemies)
        if needs_llm:
            player_pas = [{"action_type": a.action_type, "target": a.target,
                           "weapon": a.weapon, "roll": a.roll, "tier": a.tier,
                           "damage": a.damage, "damage_type": getattr(a, 'damage_type', '物理')}
                          for a in state.log if a.actor == "player"]
            rresult = cs._build_round_result(state, player_pas, [], state.round - 1)
            rresult = cs._llm_correct_round(rresult, combat_init, state.enemies,
                                             player_extra, "", "", player_pas)
            for a in state.log:
                if a.actor == "player" and a.action_type == "attack":
                    corrected = rresult.get("player_damage", a.damage)
                    if corrected != a.damage:
                        a.damage = corrected

            # ── 敌人 LLM 修正 ──
            inv_context = getattr(player, 'personal_description', '') or ''
            if getattr(player, 'extra', ''):
                inv_context = (inv_context + '\n' + player.extra).strip()
            for ea in state.log:
                if ea.actor == "player":
                    continue
                enemy = next((e for e in state.enemies if e.instance_id == ea.actor), None)
                if enemy and getattr(enemy, 'special_rules', ''):
                    ea_data = {"actor": ea.actor, "action_type": ea.weapon,
                               "roll": ea.roll, "tier": ea.tier,
                               "damage": ea.damage, "damage_type": getattr(ea, 'damage_type', '物理')}
                    corrected = cs._llm_correct_enemy_round(
                        enemy, ea_data, player, player_extra, inv_context)
                    new_dmg = max(0, int(corrected.get("damage", ea.damage)))
                    state.player_hp = max(0, state.player_hp + ea.damage - new_dmg)
                    ea.damage = new_dmg

        # 显示结果
        if pa.action_type == "dodge":
            print("  你进入了回避姿态。")
        elif pa.action_type == "flee":
            print(f"  {'✅' if pa.success else '❌'} {pa.narrative}")
        elif pa.action_type == "attack":
            s = "✓" if pa.success else "✗"
            dmg = f" 造成{pa.damage}点伤害" if pa.success and pa.damage > 0 else ""
            print(f"  {s} {pa.weapon} D100={pa.roll} {pa.tier or ''}{dmg}")

        for iid in state.initiative_order:
            if iid == "player":
                continue
            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'hp', 1) <= 0:
                continue
            for ea in state.log:
                if ea.actor == iid and ea.round_num == state.round:
                    name = getattr(enemy, 'enemy_ref', '敌人')
                    if ea.damage > 0:
                        print(f"  {name}用{ea.weapon}击中！D100={ea.roll} 造成{ea.damage}点伤害")
                    break
            if state.player_hp <= 0:
                state.finished = True
                break

        # 结算玩家伤害到敌人
        for act in state.log:
            if act.actor == "player" and act.damage > 0:
                enemy = next((e for e in state.enemies if e.instance_id == act.target), None)
                if enemy:
                    enemy.hp = max(0, getattr(enemy, 'hp', 10) - act.damage)

        state.round += 1

    outcome = "win"
    player_fled = any(a.actor == "player" and a.action_type == "flee" and a.success
                      for a in state.full_log)
    if player_fled:
        outcome = "flee"
    elif state.player_hp <= 0:
        outcome = "loss"
    elif state.round > max_rounds:
        outcome = "draw"

    print(f"\n── 战斗结束 ──")
    labels = {"win": "✅ 胜利", "loss": "💀 败北", "draw": "⏱ 平局", "flee": "🏃 逃跑成功"}
    print(f"结果: {labels.get(outcome, outcome)} | HP:{state.player_hp} 轮次:{state.round - 1}")

    # 回写
    player.derived.HP = max(0, state.player_hp)
    player.derived.SAN = max(0, state.player_san)

    # 善后
    combat_is_boss = bool(world.bosses and world.bosses.active_boss_id)
    from game.messages import CombatResult as CR
    if outcome == "flee":
        world.enemy_manager.exit_combat({"outcome": "flee"})
        if combat_is_boss:
            world.bosses.set_active(None)
    else:
        world.enemy_manager.exit_combat({"outcome": outcome})
        if combat_is_boss:
            world.bosses.resolve_outcome(CR(
                outcome=outcome, defeated_instance_ids=[],
                player_hp=state.player_hp, player_san=state.player_san,
                rounds=state.round - 1, narrative="",
            ))
            if outcome == "win":
                world.mark_completed(world.bosses.active_boss_id, "")
            world.bosses.set_active(None)

    # 生成 LLM 战斗叙事摘要
    combat_narrative = cs._generate_combat_narrative(state, player, combat_init.scene, log_dir=_log_dir)
    if combat_narrative:
        print(f"\n  📜 {combat_narrative}")

    # 写入战斗完整日志（文本格式，修正后数据）
    try:
        import os as _os
        log_path = f"{_log_dir}/combat_log_{_log_timestamp}_r{state.round-1}.txt"
        lines = []
        lines.append(f"战斗日志")
        lines.append(f"场景: {combat_init.scene}")
        lines.append(f"调查员: {getattr(player, 'name', '?')}")
        lines.append(f"回合数: {state.round - 1}")
        lines.append(f"结果: {outcome}")
        lines.append(f"HP: {state.player_hp}/{state.player_hp_max}  SAN: {state.player_san}")
        lines.append("")
        lines.append("=" * 60)
        for a in state.full_log:
            actor = "调查员" if a.actor == "player" else a.actor
            hp_str = f" HP{a.hp_before}→{a.hp_after}" if a.damage > 0 else ""
            lines.append(
                f"[R{a.round_num:02d}] {actor} | {a.action_type} | "
                f"{a.skill_name}={a.skill_value} | "
                f"D100={a.roll} {a.tier} | "
                f"伤害={a.damage}{'(' + getattr(a, 'damage_type', '') + ')' if getattr(a, 'damage_type', '物理') != '物理' else ''}{hp_str}"
                f"{' | ' + a.narrative if a.narrative else ''}"
            )
        lines.append("=" * 60)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
    except Exception:
        pass

    return {"outcome": outcome, "narrative": combat_narrative or "",
            "is_boss": combat_is_boss,
            "game_over": outcome == "loss" and not combat_is_boss}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TRPG 调查员助手 — 命令行游戏")
    parser.add_argument("--character", "-c", type=str, default=None,
                        help="调查员角色卡路径（默认：investigator/test_character.json）")
    args = parser.parse_args()
    run_game(character_path=args.character)
