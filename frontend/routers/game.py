"""frontend/routers/game.py — Game loop API + WebSocket progress stream."""
from __future__ import annotations

import json
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

router = APIRouter(tags=["game"])

TEMPLATES_DIR = FRONTEND_DIR / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Game instance (lazy init) ──
_game_instance: dict | None = None
_game_quit: bool = False  # prevents auto-reinit after /quit
_weapon_lib = None
_enemy_lib = None
_injector = None

_progress_queues: dict[str, queue.Queue] = {}

# ── Combat session storage (in-memory, per-process) ──
# Each entry: {"state": CombatState, "combat_init": CombatInit}
_combat_sessions: dict[str, dict] = {}


def _serialize_enemies_for_frontend(enemies: list) -> list[dict]:
    """Serialize enemy list for frontend display."""
    return [
        {
            "instance_id": getattr(e, 'instance_id', ''),
            "enemy_ref": getattr(e, 'enemy_ref', ''),
            "hp": getattr(e, 'hp', 0),
            "hp_max": getattr(e, 'hp_max', getattr(e, 'hp', 0)),
            "quantity": getattr(e, 'quantity', 1),
            "status": getattr(e, 'status', ''),
            "attributes": getattr(e, 'attributes', {}),
            "boss_mechanics": getattr(e, 'boss_mechanics', ''),
            "special_rules": getattr(e, 'special_rules', ''),
            "armor": getattr(e, 'armor', ''),
            "multi_attack": getattr(e, 'multi_attack', 1),
        }
        for e in enemies
    ]


def _serialize_combat_state_for_frontend(state) -> dict:
    """Serialize CombatState fields needed by frontend."""
    return {
        "round": state.round,
        "player_hp": state.player_hp,
        "player_hp_max": state.player_hp_max,
        "player_san": state.player_san,
        "enemies": _serialize_enemies_for_frontend(state.enemies),
        "initiative_order": state.initiative_order,
        "finished": state.finished,
    }


def _deserialize_enemies_for_combat(enemy_data_list: list) -> list:
    """Deserialize enemy dicts to objects usable by CombatSystem."""
    from dataclasses import dataclass, field

    @dataclass
    class _Enemy:
        instance_id: str = ""
        enemy_ref: str = ""
        hp: int = 0
        hp_max: int = 0
        status: str = ""
        quantity: int = 1
        attributes: dict = field(default_factory=dict)
        boss_mechanics: str = ""
        special_rules: str = ""
        phases: list = field(default_factory=list)
        damage_multipliers: dict = field(default_factory=dict)
        armor: str = ""
        multi_attack: int = 1
        attacks: list = field(default_factory=list)
        dex: int = 50
        dodge_bonus: int = 0
        flags: list = field(default_factory=list)

    enemies = []
    for data in enemy_data_list:
        e = _Enemy()
        for k, v in data.items():
            if hasattr(e, k):
                setattr(e, k, v)
        enemies.append(e)
    return enemies


def _init_libraries(weapon_path="", enemy_path="", boss_path=""):
    global _weapon_lib, _enemy_lib, _injector
    if _weapon_lib is not None:
        return
    from library.weapons import WeaponLibrary
    from library.enemies import EnemyLibrary
    from library.injector import ContentInjector

    _weapon_lib = WeaponLibrary()
    if weapon_path:
        _weapon_lib.load_core(str(PROJECT_ROOT / weapon_path))
    else:
        _weapon_lib.load_core()
    _enemy_lib = EnemyLibrary()
    if enemy_path:
        _enemy_lib.load_core(str(PROJECT_ROOT / enemy_path))
    else:
        _enemy_lib.load_core()
    _injector = ContentInjector(_weapon_lib, _enemy_lib)


def get_game() -> dict | None:
    global _game_instance, _game_quit
    if _game_quit:
        return None
    if _game_instance is None:
        from game_loop import init_game
        from investigator import load_investigator, Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        import os
        from datetime import datetime
        from game_loop import setup_logging
        log_dir = setup_logging()

        _init_libraries()

        g = init_game(
            l2_path=str(PROJECT_ROOT / "data/modules/测试模组0528v2/l2_keeper_test.json"),
            l1_path=str(PROJECT_ROOT / "data/modules/测试模组0528v2/l1_player.json"),
            l3_path=str(PROJECT_ROOT / "data/modules/测试模组0528v2/l3_designer.json"),
            start_node="测试房间",
        )
        char_path = str(PROJECT_ROOT / "investigator/test_character.json")
        if os.path.exists(char_path):
            inv = load_investigator(char_path)
        else:
            inv = Investigator(name="调查员A", age=25, gender="男")
            inv.stats = roll_stats()
            inv.skills = create_skill_list()
            inv.derived = calc_derived(inv.stats, inv.age)
        g["keeper"].world.set_player(inv)
        # 应用 AT_WORLD 中延后的 item_gain
        for item_gain in g.get("pending_world_items", []):
            if hasattr(inv, 'item_manager'):
                inv.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)
        _game_instance = g
    return _game_instance


@router.get("/game", response_class=HTMLResponse)
async def game_page(request: Request):
    return templates.TemplateResponse(request, "game.html", {})


def _handle_slash_command(cmd: str) -> str:
    """Handle slash commands synchronously, return HTML."""
    global _game_instance
    game = get_game()
    world = game["keeper"].world
    p = world.player
    cmd = cmd.strip().lower()
    lines = []
    if cmd == "/help":
        names = ["/scene", "/char", "/flags", "/events",
                 "/save <slot>", "/load <slot>", "/quit", "/reset", "/help"]
        lines = [f'<div class="text-xs text-gray-500">{"  ".join(names)}</div>']
    elif cmd == "/scene":
        loc = world.current_location
        desc = world.get_current_description()
        lines.append(f'<div class="font-bold text-aged-brown">{loc}</div>')
        lines.append(f'<div class="text-xs text-gray-500 mt-1">{desc}</div>')
        for e in world.get_possible_exits():
            lines.append(f'<div class="text-xs text-gray-600">→ {e.target}：{e.method}</div>')
    elif cmd == "/char":
        if p:
            lines.append(f'<div class="text-sm text-aged-gold">{p.name} (HP {p.derived.HP} SAN {p.derived.SAN})</div>')
            lines.append(f'<div class="text-xs text-gray-500">属性: {" ".join(f"{k}={getattr(p.stats,k,0)}" for k in ["STR","CON","SIZ","DEX","APP","INT","POW","EDU","LUCK"])}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">未设置调查员</div>')
    elif cmd == "/flags":
        rs = world.runtime_state or {}
        if rs:
            for k, v in rs.items():
                c = "text-green-400" if v.get("completed") else "text-gray-500"
                lines.append(f'<div class="text-xs {c}">{k}: {v}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">无状态</div>')
    elif cmd == "/events":
        triggered = world.triggered_events or []
        if triggered:
            for ev in triggered:
                lines.append(f'<div class="text-xs text-gray-400">{ev}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">无已触发事件</div>')
    elif cmd.startswith("/save"):
        slot = cmd.replace("/save", "").strip() or "1"
        try:
            from game_loop import save_game
            save_game(game, str(PROJECT_ROOT / f"save_{slot}.json"))
            lines.append(f'<div class="text-xs text-green-400">已存档到 save_{slot}.json</div>')
        except Exception as e:
            lines.append(f'<div class="text-xs text-red-400">存档失败: {e}</div>')
    elif cmd.startswith("/load"):
        slot = cmd.replace("/load", "").strip() or "1"
        spath = str(PROJECT_ROOT / f"save_{slot}.json")
        if Path(spath).exists():
            try:
                from game_loop import load_game
                load_game(game, spath)
                lines.append(f'<div class="text-xs text-green-400">已从 save_{slot}.json 读档</div>')
            except Exception as e:
                lines.append(f'<div class="text-xs text-red-400">读档失败: {e}</div>')
        else:
            lines.append(f'<div class="text-xs text-gray-500">存档 save_{slot}.json 不存在</div>')
    elif cmd in ("/quit", "/exit"):
        global _game_quit
        _game_instance = None
        _game_quit = True
        lines.append('<div class="text-xs text-green-400">游戏已退出。返回启动页以重新开始。</div>')
    elif cmd == "/reset":
        _game_instance = None
        _game_quit = False
        lines.append('<div class="text-xs text-green-400">游戏已重置，刷新页面以重新开始</div>')
    else:
        lines.append(f'<div class="text-xs text-gray-500">未知命令: {cmd}。输入 /help 查看可用命令。</div>')
    return "".join(lines)


@router.post("/api/game/turn")
async def process_turn(user_input: str = Form(...)):
    import asyncio
    import traceback
    from game_loop import run_turn

    # Check autosave flag before processing
    try:
        import game_loop as _gl
        g = get_game()
        if g:
            _gl._check_autosave(g)
    except Exception:
        pass

    # Route slash commands directly — skip LLM pipeline
    stripped = user_input.strip()
    if stripped.startswith("/"):
        cmd_html = _handle_slash_command(stripped)
        return {
            "brief": stripped,
            "narrative": "",
            "narrative_html": cmd_html,
            "combat": None,
            "skill_results": [],
            "game_over": False,
            "ending": None,
            "timestamp": "",
            "player_snapshot": None,
        }

    try:
        game = get_game()
        if game is None:
            return {
                "brief": "",
                "narrative": "",
                "narrative_html": '<div class="text-gray-500 text-sm">游戏已退出。请返回启动页重新开始。</div>',
                "combat": None,
                "skill_results": [],
                "game_over": True,
                "ending": None,
                "timestamp": "",
                "player_snapshot": None,
                "turn_dynamic_text": "",
            }
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(
            f'<div class="msg-narrative px-3 py-2 text-red-400 border-l-2 '
            f'border-red-500 bg-[#1a0a0a]">游戏引擎错误: {e}</div>'
        )

    _push_progress("parse", "running")

    # Run blocking LLM call in thread pool to avoid blocking event loop
    loop = asyncio.get_running_loop()
    try:
        turn = await loop.run_in_executor(None, run_turn, game, user_input, _weapon_lib, _enemy_lib, _injector)
    except Exception as e:
        traceback.print_exc()
        _push_progress("complete", "")
        return HTMLResponse(
            f'<div class="msg-narrative px-3 py-2 text-red-400 border-l-2 border-red-500 bg-[#1a0a0a]">'
            f'错误: {e}</div>'
        )

    _push_progress("parse", "done")
    _push_progress("judge", "done")
    _push_progress("enrich", "done")
    _push_progress("combat_entry", "done")
    _push_progress("curate", "done")
    _push_progress("narrate", "done")
    _push_progress("complete", "")

    if turn and turn.get("game_frozen"):
        return {
            "brief": "",
            "narrative": "",
            "narrative_html": (
                '<div class="msg-frozen px-4 py-3 text-red-400 border-2 border-red-600 '
                'bg-[#1a0a0a] rounded">' + (turn.get("frozen_message", "系统异常").replace("\n", "<br>")) + '</div>'
            ),
            "combat": None,
            "skill_results": [],
            "game_frozen": True,
            "frozen_message": turn.get("frozen_message", ""),
            "game_over": False,
            "ending": None,
            "timestamp": "",
            "player_snapshot": None,
        }

    narrative = turn.get("narrative", "") if turn else ""
    brief = turn.get("brief", "") if turn else ""

    # Combat: if combat_init present, return it to frontend for interactive handling
    combat_init = turn.get("combat_init") if turn else None
    combat = turn.get("combat") if turn else None
    combat_init_data = None
    if combat_init and combat_init.enemies and not combat:
        combat_init_data = {
            "enemies": _serialize_enemies_for_frontend(combat_init.enemies),
            "scene": combat_init.scene,
            "initiative_context": combat_init.initiative_context,
            "environment_actions": getattr(combat_init, 'environment_actions', []),
            "player_action": combat_init.player_action,
            "player_targets": getattr(combat_init, 'player_targets', []),
            "player_extra": getattr(combat_init, 'player_extra', ''),
        }

    skill_results = turn.get("skill_results", []) if turn else []
    game_over = turn.get("game_over", False) if turn else False
    ending = turn.get("ending") if turn else None
    timestamp = turn.get("timestamp", "") if turn else ""
    player_snapshot = turn.get("player_snapshot") if turn else None

    # Serialize PlayerFacingSnapshot to dict
    if player_snapshot and hasattr(player_snapshot, '__dataclass_fields__'):
        from dataclasses import asdict
        player_snapshot = asdict(player_snapshot)

    # Format dynamic turn text from snapshot
    turn_dynamic_text = ""
    try:
        from game_loop import format_turn_dynamic
        turn_dynamic_text = format_turn_dynamic(player_snapshot, brief, narrative)
    except Exception:
        import traceback
        traceback.print_exc()

    narrative_html = ""
    if brief:
        narrative_html += (
            f'<div class="msg-brief px-3 py-2 text-sm text-gray-400 border-l-2 '
            f'border-gray-600 mb-2">{brief}</div>'
        )
    if narrative:
        narrative_html += (
            f'<div class="msg-narrative px-3 py-2 text-parchment border-l-2 '
            f'border-aged-gold bg-[#1a1410] narrative-flash">{narrative}</div>'
        )
    if not narrative_html:
        narrative_html = (
            f'<div class="msg-brief px-3 py-2 text-sm text-gray-500">'
            f'（没有返回叙事内容）</div>'
        )

    return {
        "brief": brief,
        "narrative": narrative,
        "narrative_html": narrative_html,
        "combat": combat,
        "combat_init": combat_init_data,
        "skill_results": skill_results,
        "game_over": game_over,
        "ending": ending,
        "timestamp": timestamp,
        "player_snapshot": player_snapshot,
        "turn_dynamic_text": turn_dynamic_text,
    }


@router.get("/api/game/character-card", response_class=HTMLResponse)
async def character_card():
    game = get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-500">无调查员</span>')

    stats = p.stats
    derived = p.derived
    avatar = getattr(p, 'avatar_url', '') or ""

    # --- Header block ---
    avatar_block = (
        f'<img src="{avatar}" class="w-14 h-14 rounded-full object-cover border-2 border-gray-700" onerror="this.style.display=\'none\'">'
        if avatar else
        '<div class="w-14 h-14 rounded-full bg-gray-800 flex items-center justify-center text-gray-500 border-2 border-gray-700">'
        '<svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>'
        '</div>'
    )

    # 职业名称（兼容字符串或 Occupation 对象）
    occ_name = ""
    if p.occupation:
        occ_name = p.occupation if isinstance(p.occupation, str) else getattr(p.occupation, 'name', '')

    header = (
        f'<div class="flex items-center gap-3 pb-3 border-b border-gray-800/60">'
        f'{avatar_block}'
        f'<div class="min-w-0">'
        f'<div class="text-sm font-bold text-aged-gold truncate">{p.name}</div>'
        f'<div class="text-[10px] text-gray-500">{p.age}岁 {p.gender} {occ_name}</div>'
        f'</div></div>'
    )

    # --- Introduction: appearance + personal description ---
    intro_parts = []
    if getattr(p, 'appearance', ''):
        intro_parts.append(f'<div class="text-[10px] text-gray-400"><span class="text-gray-500">外貌：</span>{p.appearance}</div>')
    if getattr(p, 'personal_description', ''):
        intro_parts.append(f'<div class="text-[10px] text-gray-400 leading-relaxed">{p.personal_description}</div>')
    intro_html = (
        f'<div class="space-y-1.5 pt-2">{ "".join(intro_parts) }</div>'
    ) if intro_parts else ''

    # --- Stats grid (3x3) ---
    stat_labels = {"STR": "力量", "CON": "体质", "SIZ": "体型", "DEX": "敏捷", "APP": "外貌",
                   "INT": "智力", "POW": "意志", "EDU": "教育", "LUCK": "幸运"}
    stats_cells = "".join(
        f'<div class="text-center p-1.5 bg-[#1a150c]/60 rounded border border-gray-800/40">'
        f'<div class="text-[10px] text-gray-500">{stat_labels.get(k, k)}</div>'
        f'<div class="text-sm font-bold text-gray-300">{getattr(stats, k, 0)}</div>'
        f'</div>'
        for k in ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"]
    )
    stats_html = (
        f'<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">属性</div>'
        f'<div class="grid grid-cols-3 gap-1.5">{stats_cells}</div></div>'
    )

    # --- Derived stats bar ---
    hp_pct = min(100, max(0, (derived.HP / derived.HP_MAX * 100) if derived.HP_MAX else 0))
    san_pct = min(100, max(0, derived.SAN / 99 * 100))
    derived_html = (
        f'<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">状态</div>'
        f'<div class="space-y-2">'
        f'<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>HP</span><span class="text-coc-green">{derived.HP}/{derived.HP_MAX}</span></div>'
        f'<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-coc-green rounded transition-all duration-500" style="width:{hp_pct}%"></div></div></div>'
        f'<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>SAN</span><span class="text-aged-gold">{derived.SAN}</span></div>'
        f'<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-aged-gold rounded transition-all duration-500" style="width:{san_pct}%"></div></div></div>'
        f'<div class="flex gap-3 text-[10px] text-gray-400 pt-1">'
        f'<span>MP <span class="text-gray-300">{derived.MP}</span></span>'
        f'<span>MOV <span class="text-gray-300">{derived.MOV}</span></span>'
        f'<span>DB <span class="text-gray-300">{derived.DB}</span></span>'
        f'<span>BUILD <span class="text-gray-300">{derived.BUILD}</span></span>'
        f'<span>DODGE <span class="text-gray-300">{derived.DODGE}</span></span>'
        f'</div></div></div>'
    )

    # --- Skills by category ---
    skills_list = list(p.skills.values()) if isinstance(p.skills, dict) else (p.skills if isinstance(p.skills, list) else [])
    cats = {}
    for s in skills_list:
        cat = getattr(s, 'category', '其他')
        cats.setdefault(cat, []).append(s)
    cat_order = ["战斗", "操作", "感知", "知识", "社交", "其他"]
    cat_colors = {"战斗": "text-red-400/70", "操作": "text-blue-400/70", "感知": "text-green-400/70",
                  "知识": "text-purple-400/70", "社交": "text-yellow-400/70", "其他": "text-gray-500"}

    skills_sections = []
    for cat in cat_order:
        if cat not in cats:
            continue
        items = cats[cat]
        items_html = "".join(
            f'<div class="flex justify-between items-center py-0.5">'
            f'<span class="text-xs text-gray-400">{s.name}</span>'
            f'<span class="text-xs font-mono {cat_colors.get(cat, "text-gray-500")}">{s.value}%</span>'
            f'</div>'
            for s in sorted(items, key=lambda x: -x.value)
        )
        skills_sections.append(
            f'<details class="group">'
            f'<summary class="flex items-center justify-between cursor-pointer py-1 text-[10px] text-gray-500 hover:text-gray-300 list-none">'
            f'<span class="flex items-center gap-1"><span class="w-1 h-1 rounded-full {cat_colors.get(cat, "bg-gray-500")}"></span>{cat} ({len(items)})</span>'
            f'<span class="text-gray-600 group-open:rotate-180 transition-transform">▼</span>'
            f'</summary>'
            f'<div class="pl-3 border-l border-gray-800/40 ml-1 space-y-0.5">{items_html}</div>'
            f'</details>'
        )
    skills_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">技能 ({len(skills_list)})</div>'
        f'<div class="space-y-1">{"".join(skills_sections)}</div></div>'
    ) if skills_list else ''

    # --- Weapons ---
    weapons = getattr(p, 'weapons', [])
    weapons_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">武器 ({len(weapons)})</div>'
        f'<div class="space-y-1">'
        + "".join(
            f'<div class="flex justify-between text-xs text-gray-400 py-0.5">'
            f'<span>{w.name}</span><span class="text-gray-500">{getattr(w, "damage", "?")}</span>'
            f'</div>'
            for w in weapons
        )
        + '</div></div>'
    ) if weapons else ''

    # --- Items ---
    items_desc = p.item_manager.describe() if hasattr(p, 'item_manager') and p.item_manager else "无"
    items_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">物品</div>'
        f'<div class="text-xs text-gray-400 leading-relaxed">{items_desc}</div></div>'
    )

    return HTMLResponse(
        header + intro_html + stats_html + derived_html + skills_html + weapons_html + items_html
    )


@router.get("/api/game/player-status")
async def player_status(format: str = ""):
    game = get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-600">未设置调查员</span>')
    hp, san = p.derived.HP, p.derived.SAN
    has_avatar = getattr(p, 'avatar_url', '')
    occupation = getattr(p, 'occupation', '')
    occ_name = getattr(occupation, 'name', '') if occupation else ''
    if format == "json":
        return {
            "hp": hp,
            "hp_max": p.derived.HP_MAX,
            "san": san,
            "name": p.name,
            "avatar_url": has_avatar,
            "occupation": occ_name,
            "age": p.age,
            "gender": p.gender,
        }
    return HTMLResponse(
        f'<div class="text-xs"><span class="text-gray-500">HP </span><span class="text-coc-green">{hp}</span>'
        f'<span class="text-gray-500 ml-2">SAN </span><span class="text-aged-gold">{san}</span></div>'
    )


@router.post("/api/game/command", response_class=HTMLResponse)
async def game_command(cmd: str = Form(...)):
    return HTMLResponse(_handle_slash_command(cmd))


@router.get("/api/game/scene", response_class=HTMLResponse)
async def scene_info():
    game = get_game()
    world = game["keeper"].world
    loc = world.current_location
    desc = world.get_current_description()
    exits = world.get_possible_exits()
    exits_html = "".join(
        f'<div class="text-xs text-gray-600">→ {e.target}：{e.method}</div>' for e in exits
    )
    return HTMLResponse(
        f'<div class="font-bold text-aged-brown">{loc}</div>'
        f'<div class="text-xs text-gray-500 mt-1">{desc}</div>'
        f'{exits_html}'
    )


@router.websocket("/api/game/progress")
async def game_progress(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    qid = str(id(ws))
    _progress_queues[qid] = q
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                await ws.send_json(msg)
                if msg.get("step") == "complete":
                    break
            except asyncio.TimeoutError:
                await ws.send_json({"step": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        _progress_queues.pop(qid, None)


def _push_progress(step: str, status: str):
    """Send progress update to all connected WS clients."""
    import asyncio as _asyncio
    msg = {"step": step, "status": status}
    for q in list(_progress_queues.values()):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


@router.post("/api/game/init")
async def init_game_api(
    request: Request,
    l1_path: str = Form(""),
    l2_path: str = Form(""),
    l3_path: str = Form(""),
    char_path: str = Form(""),
    weapon_path: str = Form(""),
    enemy_path: str = Form(""),
    boss_path: str = Form(""),
):
    global _game_instance, _game_quit
    _game_quit = False
    import os
    from datetime import datetime
    from game_loop import init_game
    from investigator import load_investigator, Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    from prompts import set_prompt_log_dir
    from llm import set_llm_log_dir

    # Default paths if empty
    if not l2_path:
        l2_path = "data/modules/测试模组0528v2/l2_keeper_test.json"
    if not l1_path:
        l1_path = "data/modules/测试模组0528v2/l1_player.json"
    if not l3_path:
        l3_path = "data/modules/测试模组0528v2/l3_designer.json"

    # Initialize libraries with user-specified paths
    _init_libraries(weapon_path, enemy_path, boss_path)

    from game_loop import setup_logging
    log_dir = setup_logging()

    # Determine start scene: L3.start_scene > L3.scene_intents first key > L2 first scene
    start_node = _resolve_start_scene(l2_path, l3_path)

    try:
        g = init_game(
            l2_path=str(PROJECT_ROOT / l2_path),
            l1_path=str(PROJECT_ROOT / l1_path),
            l3_path=str(PROJECT_ROOT / l3_path),
            start_node=start_node,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    if char_path and os.path.exists(str(PROJECT_ROOT / char_path)):
        try:
            inv = load_investigator(str(PROJECT_ROOT / char_path))
        except Exception:
            inv = _make_default_inv()
    else:
        inv = _make_default_inv()

    g["keeper"].world.set_player(inv)
    # 应用 AT_WORLD 中延后的 item_gain
    for item_gain in g.get("pending_world_items", []):
        if hasattr(inv, 'item_manager'):
            inv.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)
    _game_instance = g

    from game_loop import start_autosave
    start_autosave(g)

    # Fire initial turn to trigger scene auto_triggers
    initial_brief = ""
    initial_narrative = ""
    try:
        from game_loop import run_turn
        initial = run_turn(g, "[游戏开始]", _weapon_lib, _enemy_lib, _injector)
        initial_brief = initial.get("brief", "") if initial else ""
        initial_narrative = initial.get("narrative", "") if initial else ""
    except Exception:
        pass

    return {
        "success": True,
        "location": g["keeper"].world.current_location,
        "hp": inv.derived.HP,
        "san": inv.derived.SAN,
        "name": inv.name,
        "initial_brief": initial_brief,
        "initial_narrative": initial_narrative,
    }


@router.get("/api/game/state")
async def game_state():
    game = get_game()
    world = game["keeper"].world
    p = world.player
    return {
        "location": world.current_location,
        "turn": game["keeper"].turn_number,
        "hp": p.derived.HP if p else 0,
        "san": p.derived.SAN if p else 0,
        "name": p.name if p else "",
    }


@router.post("/api/combat/start")
async def combat_start(request: Request):
    """Initialize a combat session from a CombatInit object.

    Request body JSON:
        {"combat_init": {... serialized CombatInit ...}}
    """
    import json, uuid
    from game.combat import CombatSystem
    from game.messages import CombatInit

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    combat_init_data = data.get("combat_init", {})

    game = get_game()
    if game is None:
        return JSONResponse({"error": "游戏未初始化"}, status_code=400)

    player = game["keeper"].world.player
    if not player:
        return JSONResponse({"error": "未设置调查员"}, status_code=400)

    # Reconstruct CombatInit with live player
    enemies = _deserialize_enemies_for_combat(combat_init_data.get("enemies", []))
    combat_init = CombatInit(
        enemies=enemies,
        player=player,
        scene=combat_init_data.get("scene", ""),
        initiative_context=combat_init_data.get("initiative_context", ""),
        environment_actions=combat_init_data.get("environment_actions", []),
        player_action=combat_init_data.get("player_action", ""),
        player_targets=combat_init_data.get("player_targets", []),
        player_extra=combat_init_data.get("player_extra", ""),
    )

    cs = CombatSystem()
    state = cs._init_combat(combat_init)

    session_id = str(uuid.uuid4())[:8]
    _combat_sessions[session_id] = {
        "state": state,
        "combat_init": combat_init,
    }

    available = cs._get_player_actions(player, getattr(combat_init, 'environment_actions', []))
    actions = [{"id": a["id"], "label": a["label"],
                "multi_attack": a.get("multi_attack", 1),
                "damage_type": a.get("damage_type", "物理")}
               for a in available]

    return {
        "session_id": session_id,
        "state": _serialize_combat_state_for_frontend(state),
        "actions": actions,
    }


@router.post("/api/combat/round")
async def combat_round(request: Request):
    """Execute one combat round.

    Request body JSON:
        {"session_id": "...", "action_id": "...", "target_ids": [...], "player_extra": "..."}
    """
    import json
    from game.combat import CombatSystem

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    session_id = data.get("session_id", "")

    session = _combat_sessions.get(session_id)
    if not session:
        return JSONResponse({"error": "战斗会话不存在或已过期"}, status_code=400)

    state = session["state"]
    combat_init = session["combat_init"]
    action_id = data.get("action_id", "punch")
    target_ids = data.get("target_ids", [])
    player_extra = data.get("player_extra", "")

    cs = CombatSystem()
    result = cs.run_single_round(combat_init, state, action_id, target_ids, player_extra)

    # Update session with mutated state
    session["state"] = state

    # Serialize round_log for JSON response
    round_log = []
    for a in result.get("round_log", []):
        round_log.append({
            "actor": getattr(a, 'actor', ''),
            "action_type": getattr(a, 'action_type', ''),
            "weapon": getattr(a, 'weapon', ''),
            "skill_name": getattr(a, 'skill_name', ''),
            "skill_value": getattr(a, 'skill_value', 0),
            "roll": getattr(a, 'roll', 0),
            "tier": getattr(a, 'tier', ''),
            "target": getattr(a, 'target', ''),
            "damage": getattr(a, 'damage', 0),
            "damage_type": getattr(a, 'damage_type', '物理'),
            "hp_before": getattr(a, 'hp_before', 0),
            "hp_after": getattr(a, 'hp_after', 0),
            "narrative": getattr(a, 'narrative', ''),
            "success": getattr(a, 'success', False),
            "round_num": getattr(a, 'round_num', 0),
        })

    # Generate combat narrative on finish
    combat_narrative = ""
    if result.get("finished"):
        try:
            from prompts import _log_dir as prompt_log_dir
            combat_narrative = cs._generate_combat_narrative(
                state, combat_init.player, combat_init.scene,
                log_dir=prompt_log_dir or "")
        except Exception:
            pass
        # Write HP/SAN back to player
        if combat_init.player:
            combat_init.player.derived.HP = max(0, state.player_hp)
            combat_init.player.derived.SAN = max(0, state.player_san)

        g = get_game()
        if g:
            world = g["keeper"].world
            keep = g["keeper"]
            narr = g["narrator"]
            if result.get("outcome") == "win":
                boss_id = world.bosses.active_boss_id if world.bosses else None
                if boss_id:
                    world.get_runtime_state(boss_id).completed = True
                    world.bosses.set_active(None)
            world.enemies.exit_combat({"outcome": result.get("outcome", "")})

            # Combat completion: re-enrich + curate with combat result (same turn)
            combat_result = {
                "outcome": result.get("outcome", ""),
                "narrative": combat_narrative or "",
                "is_boss": result.get("is_boss", False),
            }
            completed = keep.complete_combat_turn(keep._last_player_input, combat_result) if keep._last_player_input else {}
            completed_brief = ""
            completed_narrative = ""
            if completed.get("brief"):
                try:
                    snap = world.build_snapshot()
                    completed_brief, completed_narrative, _ = narr.narrate(
                        completed["brief"], snap=snap, user_input=keep._last_player_input)
                    from game.turn_logger import TurnLogger
                    from game_loop import _turn_logger as tl
                    if tl:
                        tl.log(
                            player_input=keep._last_player_input,
                            enrich_result=completed.get("enrich"),
                            narrator_brief=completed_brief,
                            narrator_narrative=completed_narrative,
                        )
                except Exception:
                    pass
            keep._last_player_input = ""

        return {
            "session_id": session_id,
            "state": _serialize_combat_state_for_frontend(state),
            "finished": True,
            "outcome": result.get("outcome"),
            "round_log": round_log,
            "round_narrative": result.get("round_narrative", ""),
            "combat_narrative": combat_narrative,
            "is_boss": result.get("is_boss", False),
            "game_over": result.get("game_over", False),
            "round": state.round,
            "combat_completed": bool(completed_brief),
            "combat_completed_brief": completed_brief,
            "combat_completed_narrative": completed_narrative,
        }

    return {
        "session_id": session_id,
        "state": _serialize_combat_state_for_frontend(state),
        "finished": result.get("finished", False),
        "outcome": result.get("outcome"),
        "round_log": round_log,
        "round_narrative": result.get("round_narrative", ""),
        "combat_narrative": combat_narrative,
        "is_boss": result.get("is_boss", False),
        "game_over": result.get("game_over", False),
        "round": result.get("round", 1),
    }

    # On combat finish, mark boss as completed and clean up enemy manager
    if result.get("finished") and result.get("outcome") == "win":
        g = get_game()
        if g:
            world = g["keeper"].world
            boss_id = world.bosses.active_boss_id if world.bosses else None
            if boss_id:
                world.get_runtime_state(boss_id).completed = True
                world.bosses.set_active(None)
            world.enemies.exit_combat({"outcome": "win"})


@router.get("/api/game/npcs", response_class=HTMLResponse)
async def npc_list():
    game = get_game()
    world = game["keeper"].world
    npcs = world.npcs or []
    if not npcs or not hasattr(npcs, 'get_in_scene'):
        return HTMLResponse('<span class="text-xs text-gray-500">无 NPC</span>')
    visible = npcs.get_in_scene(world.current_location)
    if not visible:
        return HTMLResponse('<span class="text-xs text-gray-500">当前场景无 NPC</span>')
    cards = ""
    for n in visible:
        att = n.attitude or "neutral"
        att_cls = {"hostile": "text-red-400", "wary": "text-yellow-400", "friendly": "text-green-400"}.get(att, "text-gray-400")
        cards += (f'<div class="text-xs flex gap-2 py-1"><span class="text-gray-300">{n.name}</span>'
                  f'<span class="{att_cls}">[{att}]</span></div>')
    return HTMLResponse(cards)


def _resolve_start_scene(l2_path: str, l3_path: str) -> str:
    """Determine the starting scene for game init.

    Priority:
    1. L3 JSON top-level 'start_scene' field
    2. L3 JSON module_meta.start_scene
    3. First key in L3 scene_intents dict
    4. First key in L2 scenes dict
    5. Fallback: "测试房间"
    """
    import json as _json
    l2_full = PROJECT_ROOT / l2_path
    l3_full = PROJECT_ROOT / l3_path

    # Try L3 first
    if l3_full.exists():
        try:
            l3 = _json.loads(l3_full.read_text(encoding="utf-8"))
            # Check top-level start_scene
            if isinstance(l3, dict):
                if "start_scene" in l3 and l3["start_scene"]:
                    return l3["start_scene"]
                # Check module_meta.start_scene
                meta = l3.get("module_meta", {})
                if isinstance(meta, dict) and meta.get("start_scene"):
                    return meta["start_scene"]
                # First scene_intents key
                si = l3.get("scene_intents", {})
                if isinstance(si, dict) and si:
                    return next(iter(si.keys()))
        except Exception:
            pass

    # Try L2 scenes dict
    if l2_full.exists():
        try:
            l2 = _json.loads(l2_full.read_text(encoding="utf-8"))
            scenes = l2.get("scenes", {})
            if isinstance(scenes, dict) and scenes:
                return next(iter(scenes.keys()))
        except Exception:
            pass

    return "测试房间"


def _make_default_inv():
    from investigator import Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    inv = Investigator(name="调查员", age=25, gender="男")
    inv.stats = roll_stats()
    inv.skills = create_skill_list()
    inv.derived = calc_derived(inv.stats, inv.age)
    return inv
