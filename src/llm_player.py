"""
LLM-driven TRPG player for automated module testing.
Usage: python -m llm_player [--module NAME] [--turns N] [--profile PATH]
"""
from __future__ import annotations
import sys, os, json, time, argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm import call_deepseek
from config_llm import LLM_FLASH_MODEL, RE_INTENT_DETECTOR
from game_loop import init_game, run_turn, setup_logging
from game.turn_logger import TurnLogger
from investigator import load_investigator
from llm_player_prompts import (
    PLAYER_SYSTEM, PLAYER_USER_TEMPLATE,
    MEMORY_COMPRESS_SYSTEM, MEMORY_COMPRESS_TEMPLATE,
    TEST_MODE_STRESS, TEST_MODE_EXPLORATION, TEST_MODE_ROLEPLAY,
)


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_player_prompt(
    world, narrative_result: dict, short_history: list[str],
    long_memory: str, profile: dict,
    player_snapshot=None,
) -> tuple[str, str]:
    from game_loop import format_turn_dynamic
    snap = world.build_snapshot()
    p = snap.get("player", {})
    weapons = ", ".join(str(w) for w in p.get("weapons", [])) or "无"
    inv = p.get("inventory", "") or "无"
    loc = snap.get("location", "?")
    desc = snap.get("description", "")[:200]
    npcs_raw = snap.get("npcs_in_scene", [])
    npcs = ", ".join(n["name"] for n in npcs_raw) or "无"
    npc_states = "、".join(
        f"{n['name']}({n.get('state','?')}{', 跟随中' if n.get('following') else ''})"
        for n in npcs_raw
    ) or "无"

    # Exits
    exits = snap.get("exits", [])
    exits_text = "、".join(f"{e['target']}({e['method']})" for e in exits) or "无已知出口"

    # Enemies
    enemies = snap.get("enemies_in_scene", [])
    enemy_text = "、".join(f"{e['enemy_ref']}×{e.get('quantity',1)}[{e.get('status','?')}]" for e in enemies) or "无"

    # Time
    t = snap.get("time", {})
    gt = int(t.get("game_time", 0)) if t else 0
    day = gt // 1440 if gt else 0
    hour_val = (gt % 1440) // 60 if gt else 0
    min_val = gt % 60
    if hour_val < 5: tod = "夜间"
    elif hour_val < 8: tod = "早晨"
    elif hour_val < 17: tod = "白天"
    elif hour_val < 20: tod = "黄昏"
    else: tod = "夜间"
    time_text = f"第{day}天 {tod} {int(hour_val):02d}:{int(min_val):02d}" if gt else "游戏开始"

    brief = narrative_result.get("brief", "")
    narrative = narrative_result.get("narrative", "")
    turn_output = format_turn_dynamic(player_snapshot, brief, narrative)

    test_mode = profile.get("test_mode", "exploration")
    strategy = ", ".join(profile.get("player_strategy", []))

    if test_mode == "stress":
        mode_section = TEST_MODE_STRESS.format(player_strategy=strategy)
    elif test_mode == "roleplay":
        mode_section = TEST_MODE_ROLEPLAY
    else:
        mode_section = TEST_MODE_EXPLORATION

    system = PLAYER_SYSTEM.format(test_mode_section=mode_section)
    user = PLAYER_USER_TEMPLATE.format(
        hp=p.get("hp", "?"), max_hp=p.get("max_hp", "?"),
        san=p.get("san", "?"), mp=p.get("mp", "?"),
        weapons=weapons, inventory=inv,
        location=loc, description=desc, npcs=npcs, npc_states=npc_states,
        exits=exits_text, enemies=enemy_text, time=time_text,
        turn_output=turn_output,
        short_history="\n".join(short_history[-5:]) or "（游戏开始）",
        long_memory=long_memory or "（无）",
    )
    return system, user


def compress_memory(short_history: list[str]) -> str:
    prompt = MEMORY_COMPRESS_TEMPLATE.format(
        short_history="\n".join(short_history),
    )
    try:
        result = call_deepseek(
            prompt, json_mode=False, system=MEMORY_COMPRESS_SYSTEM,
            model=LLM_FLASH_MODEL, reasoning_effort="low",
        )
        return result.strip()
    except Exception:
        return "（记忆压缩失败）"


def run_llm_player(profile_path: str = "data/stress_profile.json", module_name: str = None,
                   max_turns: int = None, max_duration_s: int = None):
    profile = load_profile(profile_path)
    pc = profile["player_config"]
    if module_name is None:
        module_name = pc["module_name"]
    if max_turns is None:
        max_turns = pc["max_turns"]
    if max_duration_s is None:
        max_duration_s = pc["max_duration_s"]

    module_dir = PROJECT_ROOT / "data" / "modules" / module_name
    l2_name = "l2_keeper_test.json" if (module_dir / "l2_keeper_test.json").exists() else "l2_keeper.json"
    l1_name = "l1_player.json"
    l3_name = "l3_designer.json"
    game = init_game(
        l2_path=str(module_dir / l2_name),
        l1_path=str(module_dir / l1_name),
        l3_path=str(module_dir / l3_name),
        start_node="6号车厢",
    )

    # Ensure a player is always set (default investigator if none provided)
    if game["keeper"].world.player is None:
        from investigator import load_investigator, Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        char_path = PROJECT_ROOT / "data" / "investigator" / "combat_test_character.json"
        if char_path.exists():
            game["keeper"].world.set_player(load_investigator(str(char_path)))
        else:
            inv = Investigator(name="测试调查员", age=25, gender="男")
            inv.stats = roll_stats()
            inv.skills = create_skill_list()
            inv.derived = calc_derived(inv.stats, inv.age)
            game["keeper"].world.set_player(inv)
    # 应用 AT_WORLD 延后的 item_gain
    for item_gain in game.get("pending_world_items", []):
        if hasattr(game["keeper"].world.player, 'item_manager'):
            game["keeper"].world.player.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)

    # Combat is short-circuited in game_loop.run_turn() (auto-win, Pyrrhic victory narrative).
    # CombatSystem.run_combat() is only used in standalone smoke tests.

    # Buff investigator only in stress mode with combat testing enabled
    ct = profile.get("combat_testing", {})
    test_mode = profile.get("test_mode", "exploration")
    if test_mode == "stress" and ct.get("mode") == "buff_investigator":
        char_path = PROJECT_ROOT / "data" / "investigator" / "combat_test_character.json"
        if char_path.exists():
            game["keeper"].world.set_player(load_investigator(str(char_path)))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = str(PROJECT_ROOT / "logs" / "llm_player" / ts)
    import os as _os
    _os.makedirs(log_dir, exist_ok=True)
    from llm import set_llm_log_dir
    from prompts import set_prompt_log_dir
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)
    turn_logger = TurnLogger(log_dir=log_dir)
    from game_loop import set_turn_logger
    set_turn_logger(turn_logger)

    def _log_player_call(turn: int, system_prompt: str, user_prompt: str, response):
        """Write full player LLM interaction (system + user + response) to log."""
        import os as _os
        player_log_path = _os.path.join(log_dir, "player_llm.txt")
        resp_str = json.dumps(response, ensure_ascii=False, indent=2) if isinstance(response, dict) else str(response)
        with open(player_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Turn {turn}\n")
            f.write(f"{'='*60}\n")
            f.write(f"--- System ---\n{system_prompt}\n\n")
            f.write(f"--- User ---\n{user_prompt}\n\n")
            f.write(f"--- Response ---\n{resp_str}\n\n")

    short_history: list[str] = []
    long_memory = ""
    compress_interval = pc["memory_compress_interval"]
    summary_log: list[dict] = []

    player_name = game["keeper"].world.player.name

    print(f"LLM Player — {module_name}")
    print(f"  Player: {player_name}, Model: {LLM_FLASH_MODEL}")
    print(f"  Strategy: {profile.get('player_strategy', [])}")
    print(f"  Max turns: {max_turns}, Max duration: {max_duration_s}s")
    print(f"  Log: {log_dir}")
    print()

    t0 = time.perf_counter()
    turn = 0
    last_narrative = {"brief": "", "narrative": ""}
    last_snapshot = None

    while turn < max_turns:
        elapsed = time.perf_counter() - t0
        if elapsed > max_duration_s:
            print(f"  Timeout at turn {turn}")
            break

        t_turn = time.perf_counter()
        try:
            system, user = build_player_prompt(
                game["keeper"].world, last_narrative,
                short_history, long_memory, profile,
                player_snapshot=last_snapshot,
            )
        except Exception as e:
            print(f"  [WARN] build_player_prompt failed: {e}")
            action = "环顾四周"
            reasoning = "prompt build error"
            system, user = "", ""

        try:
            response = call_deepseek(
                user, json_mode=True, system=system,
                model=LLM_FLASH_MODEL, reasoning_effort=RE_INTENT_DETECTOR,
                fallback_schema={"action": "环顾四周", "reasoning": "fallback"},
                max_retries=3, timeout=300,
            )
            if isinstance(response, str):
                response = json.loads(response)
            action = response.get("action", "环顾四周")
            reasoning = response.get("reasoning", "")
            _log_player_call(turn + 1, system, user, json.dumps(response, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"  [WARN] LLM call failed: {e}")
            action = "环顾四周"
            reasoning = f"LLM error: {e}"

        try:
            result = run_turn(game, action)
        except Exception as e:
            print(f"  [WARN] run_turn failed: {e}")
            result = {"brief": str(e), "narrative": "", "skill_results": [],
                      "ending": None, "combat": None, "npc_events": []}

        dt = time.perf_counter() - t_turn

        brief = result.get("brief", "")
        narrative = result.get("narrative", "")
        skill_results = result.get("skill_results", [])
        ending = result.get("ending")
        combat = result.get("combat")
        npc_events = result.get("npc_events", [])

        short_history.append(
            f"T{turn+1}: {action} → {str(brief)[:80]}"
        )
        last_narrative = {"brief": brief, "narrative": narrative}
        last_snapshot = result.get("player_snapshot")

        clock = game["keeper"].world.clock
        time_state = {
            "day": clock.day,
            "hour": clock.hour,
            "time_of_day": clock.time_of_day,
            "game_time_minutes": clock.game_time,
        }
        summary_log.append({
            "turn": turn + 1, "input": action, "reasoning": reasoning,
            "brief": brief, "narrative": narrative,
            "skill_results": skill_results,
            "combat": combat,
            "npc_events": npc_events,
            "npcs_visible": result.get("npcs_visible", {"in_scene": [], "following": []}),
            "ending": ending.get("name") if ending else None,
            "elapsed_s": round(dt, 1),
            "time_state": time_state,
            "time_agent": result.get("time_agent"),
        })

        print(f"  T{turn+1:02d} [{dt:.1f}s]: {action[:50]}")
        if reasoning:
            print(f"    -> {reasoning[:60]}")

        if ending and ending.get("game_over"):
            print(f"  Game Over: {ending.get('name', '?')}")
            break

        if (turn + 1) % compress_interval == 0:
            before_compress = list(short_history)
            long_memory = compress_memory(short_history)
            _log_player_call(turn + 1, MEMORY_COMPRESS_SYSTEM,
                           MEMORY_COMPRESS_TEMPLATE.format(short_history="\n".join(before_compress)),
                           long_memory)
            short_history = []

        turn += 1

    total_elapsed = time.perf_counter() - t0
    with open(os.path.join(log_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "module": module_name, "player": player_name,
            "turns": len(summary_log), "total_elapsed_s": round(total_elapsed, 1),
            "game_over": summary_log[-1].get("ending") if summary_log else None,
            "profile": profile,
            "turns_detail": summary_log,
        }, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(summary_log)} turns, {total_elapsed:.0f}s")
    print(f"Log: {log_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-driven TRPG player")
    parser.add_argument("--module", type=str, default=None, help="Module name")
    parser.add_argument("--turns", type=int, default=None, help="Max turns")
    parser.add_argument("--profile", type=str, default="data/stress_profile.json")
    args = parser.parse_args()
    run_llm_player(
        profile_path=args.profile, module_name=args.module,
        max_turns=args.turns,
    )
