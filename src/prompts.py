"""
Prompt 构建器 —— 为 LLM 调用链构建结构化 prompt。

所有 build_* 函数只负责构造 prompt 字符串，不发起 LLM 调用。
通过 set_prompt_log_dir() 配置日志输出路径。
"""

from __future__ import annotations
import json
import os
import re
from typing import TYPE_CHECKING

from config import SHOW_NON_TRIGGERABLE, SHOW_COMPLETED

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld
    from module_designer.l1_player import SceneL1
    from module_designer.l3_designer import L3Designer

# ── 日志配置 ──

_log_dir: str | None = None


_current_round: int = 0


def set_current_round(n: int):
    """设置当前回合数，用于日志标记。"""
    global _current_round
    _current_round = n


def set_prompt_log_dir(log_dir: str):
    """设置 prompt 日志目录。所有 build_* 函数会将 prompt 写入该目录下的独立文件。"""
    global _log_dir
    _log_dir = log_dir
    os.makedirs(_log_dir, exist_ok=True)



def _sanitize_label(label: str) -> str:
    """将标签转换为合法文件名。"""
    s = label.lower().replace(" — ", "_").replace(" ", "_").replace("—", "_")
    return ''.join(c if c.isalnum() or c == '_' else '_' for c in s)


def _show_prompt(label: str, content: str, log_dir: str | None = None, system: str | None = None):
    """将 prompt 写入日志目录下的独立文件（如已配置）。"""
    d = log_dir or _log_dir
    if not d:
        return
    from llm import set_log_label
    set_log_label(_sanitize_label(label))
    os.makedirs(d, exist_ok=True)
    filename = f"{_sanitize_label(label)}.txt"
    path = os.path.join(d, filename)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"{'='*60}\n")
        f.write(f"=== Round {_current_round} | {label} ===\n")
        f.write(f"{'='*60}\n")
        if system:
            f.write(f"--- SYSTEM ---\n{system}\n\n--- USER ---\n")
        f.write(content)
        f.write("\n\n")


def log_skill_result(text: str, log_path: str | None = None):
    """将技能检定结果写入日志文件（如已配置）。可指定路径避免并行竞态。"""
    if log_path:
        path = log_path
    elif _log_dir:
        path = os.path.join(_log_dir, "skill_checks.txt")
    else:
        return
    import threading
    lock = getattr(log_skill_result, '_lock', None)
    if lock is None:
        lock = threading.Lock()
        log_skill_result._lock = lock
    with lock:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"--- 技能检定 ---\n")
            f.write(text)
            f.write("\n\n")


def apply_trait_enhancement(player, skill_name: str, skill_detail: str,
                            entity_name: str = "", search_context: bool = False,
                            player_input: str = "",
                            graded_tiers: dict | None = None) -> tuple[str, dict | None]:
    """共享的 trait enhancement 逻辑 — judge/search/standoff 三处复用。
    
    Returns (new_tier, enhancement_dict_or_None).
    """
    inv_desc = getattr(player, 'personal_description', '') or \
               getattr(player, 'description', '')
    if not inv_desc:
        return "", None
    import re as _re
    from llm import evaluate_trait_enhancement
    roll_m = _re.search(r'D100=(\d+)/', skill_detail)
    dice_roll = int(roll_m.group(1)) if roll_m else 0
    skill_val = player.get_skill_value(skill_name) if player else 0
    enh = evaluate_trait_enhancement(
        inv_desc=inv_desc, skill_name=skill_name, skill_detail=skill_detail,
        dice_roll=dice_roll, skill_value=skill_val, entity_name=entity_name,
        search_context=search_context, player_input=player_input,
        graded_tiers=graded_tiers,
    )
    log_skill_result(f"[特质增强完整响应] {json.dumps(enh, ensure_ascii=False)}")
    new_tier = enh.get("tier", "")
    if new_tier:
        reason = enh.get("reason", "")
        detail_override = enh.get("detail_override")
        skill_detail += f"\n  [特质修正] {new_tier}：{reason}"
        if detail_override:
            skill_detail += f"\n  修正描述：{detail_override}"
        log_skill_result(skill_detail)
    return new_tier, enh


# ── 场景上下文（确定性，不依赖 LLM）──

def _build_scene_context(snap: dict) -> str:
    """Get current scene position, description, and exits from snapshot."""
    exit_list = "\n".join([
        f"  → {e['target']}：{e['method']}" for e in snap.get("exits", [])
    ]) or "（无）"
    return f"""【当前位置】{snap['location']}
【场景描述】{snap['description']}

【可移动方向】
{exit_list}"""


def _build_investigator_info(snap: dict) -> str:
    """构建调查员基本信息（从 snapshot player 字段）"""
    p = snap.get("player", {})
    if not p or not p.get("name"):
        return ""
    parts = [f"  姓名：{p['name']}"]
    if p.get("description"):
        parts.append(f"  描述：{p['description']}")
    return "【调查员】\n" + "\n".join(parts) + "\n"


def _build_player_state(snap: dict) -> str:
    """构建调查员状态块（HP/SAN/武器/物品）"""
    p = snap.get("player", {})
    if not p:
        return ""
    lines = ["【调查员状态】"]
    lines.append(f"  HP={p.get('hp', '?')} SAN={p.get('san', '?')} MP={p.get('mp', '?')}")
    if p.get("weapons"):
        lines.append(f"  武器：{', '.join(p['weapons'])}")
    inv = p.get("inventory", "")
    if inv and inv != "（未持有物品）":
        lines.append(f"  物品：{inv}")
    return "\n".join(lines) + "\n"


def _build_scene_state(snap: dict) -> str:
    """构建场景现状（NPC/敌人/武器）"""
    parts = []
    npcs = snap.get("npcs_in_scene", [])
    if npcs:
        parts.append(f"  NPC：{'、'.join(n['name'] for n in npcs)}")
    enemies = snap.get("enemies_in_scene", [])
    if enemies:
        parts.append(f"  敌人：{'、'.join(e['enemy_ref'] for e in enemies)}")
    weps = snap.get("scene_weapons", [])
    if weps:
        parts.append(f"  场景武器：{'、'.join(w['weapon_ref'] for w in weps)}")
    if not parts:
        return ""
    return "【场景现状】\n" + "\n".join(parts) + "\n"


def _build_time_block(snap: dict) -> str:
    """构建时间上下文块"""
    t = snap.get("time", {})
    if not t:
        return ""
    lines = [f"【时间】第{t.get('day', 0)}天 {t.get('time_of_day', '')}（累计{t.get('game_time', 0)}分钟）"]
    ctx = t.get("time_context", "")
    if ctx:
        lines.append(ctx)
    return "\n".join(lines) + "\n"


def _build_world_state(snap: dict) -> str:
    """从 snapshot 获取当前状态摘要"""
    runtime = snap.get("runtime", {})
    triggered = runtime.get("triggered_events", [])
    completed = runtime.get("completed", [])
    flags_str = ", ".join(completed) or "（无）"
    return f"""已触发事件：{triggered or '（无）'}
世界标记：{flags_str}"""

# ── 叙事输出解析 ──

def _build_l1l3_context(
    l1_scene: "SceneL1 | None" = None,
    l3_data: "L3Designer | None" = None,
    scene_name: str = "",
) -> str:
    """构建 L1 + L3 增强上下文，供叙事/即兴 prompt 使用."""
    parts = []
    if l3_data:
        parts.append("【基调约束】")
        # Normalize dict/dataclass access (L3 may be raw dict from JSON)
        _l3_get = lambda obj, key, default="": obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
        tc = _l3_get(l3_data, "tone_constraints", {})
        if tc:
            tc_genre = _l3_get(tc, "genre", "")
            if tc_genre:
                parts.append(f"  类型：{tc_genre}")
            tc_style = _l3_get(tc, "narrative_style", "")
            if tc_style:
                parts.append(f"  叙事风格：{tc_style}")
            tc_forbidden = _l3_get(tc, "forbidden", [])
            if tc_forbidden:
                parts.append(f"  禁止：{', '.join(tc_forbidden)}")
            tc_recommended = _l3_get(tc, "recommended", [])
            if tc_recommended:
                parts.append(f"  必须包含：{', '.join(tc_recommended)}")
        driving_force = _l3_get(l3_data, "driving_force", "")
        if driving_force:
            parts.append(f"  核心驱动力：{driving_force}")
        scene_intents = _l3_get(l3_data, "scene_intents", {})
        intent = None
        if scene_name and scene_intents:
            if isinstance(scene_intents, dict):
                intent = scene_intents.get(scene_name)
            else:
                intent = getattr(scene_intents, scene_name, None)
        if intent:
            intent_purpose = _l3_get(intent, "purpose", "")
            if intent_purpose:
                parts.append(f"  本场景设计意图：{intent_purpose}")
    if l1_scene:
        parts.append("【场景感知信息】")
        # L1 may be dict (from JSON) or dataclass — accept both
        _get = lambda obj, key, default="": obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
        desc = _get(l1_scene, "description", "")
        atm = _get(l1_scene, "atmosphere", "")
        mood = _get(l1_scene, "mood", "")
        hints = _get(l1_scene, "ambient_hints", [])
        if desc:
            parts.append(f"  描述：{desc}")
        if atm:
            parts.append(f"  氛围：{atm}")
        if mood:
            parts.append(f"  情绪基调：{mood}")
        if hints:
            parts.append(f"  环境暗示：{', '.join(hints)}")
    return "\n".join(parts) if parts else ""


def parse_narrative_output(response: dict | str) -> tuple[str, str, str]:
    """Parse narrator LLM response. Returns (brief, narrative, scene_update).
    Handles JSON dict input (new format), with fallback to string parsing (old format)."""
    if isinstance(response, dict):
        brief = response.get("brief", "")
        narrative = response.get("narrative", "")
        scene_update = response.get("scene_update", "")
        return brief, narrative, scene_update or ""

    # Fallback: string response — try old ### marker format or triple newline
    text = response
    if isinstance(text, str) and "### 结果" in text and "### 沉浸式叙事" in text:
        _, rest = text.split("### 结果", 1)
        result_part, rest2 = rest.split("### 沉浸式叙事", 1)
        brief = result_part.strip().strip(chr(34)+chr(39)+chr(0x201C)+chr(0x201D)+chr(0x2018)+chr(0x2019))
        scene_update = ""
        if "### 场景变化" in rest2:
            narrative_part, scene_part = rest2.split("### 场景变化", 1)
            scene_update = scene_part.strip().strip(chr(34)+chr(39)+chr(0x201C)+chr(0x201D)+chr(0x2018)+chr(0x2019))
            if scene_update == chr(26080) or not scene_update:
                scene_update = ""
        else:
            narrative_part = rest2
        narrative = narrative_part.strip().strip(chr(34)+chr(39)+chr(0x201C)+chr(0x201D)+chr(0x2018)+chr(0x2019))
        return brief, narrative, scene_update

    fb = text[:60] + "..." if len(text) > 60 else text
    return fb, text, ""


# ── Keeper: Parse (Step 1) ──



def _build_entity_lines(world) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str], list[str], list[str]]:
    """Build triggerable / non-triggerable / completed entity lists.

    Returns (triggerable_scene, non_triggerable_scene, triggerable_npc,
             non_triggerable_npc, triggerable_events, non_triggerable_events,
             completed_scene, completed_npc).
    NPC entities are resolved dynamically from NPC profiles based on NPC location.
    """
    node = world._current_node()

    trig_scene = []
    nontrig_scene = []
    trig_npc = []
    nontrig_npc = []

    def _split_req(entity) -> tuple[str, str, bool]:
        """Split entity requirement by ||: hard (before) | soft (after).
        Returns (hard_str, soft_str, hard_met)."""
        req = getattr(entity, 'requirement', '') or ''
        if not req.strip():
            return "", "", True
        if "||" in req:
            hard, soft = req.split("||", 1)
            hard, soft = hard.strip(), soft.strip()
        else:
            hard, soft = req.strip(), ""
        if not hard:
            return "", soft, True
        if hard.startswith("flag:"):
            from scenario_core import parse_hard_requirement
            met = parse_hard_requirement(hard, world.runtime_state)
        else:
            met = world.are_entity_requirements_met(entity)
        return hard, soft, met

    def _fmt_inter(entity, prefix: str = "[INTERACT]") -> str:
        """Format an interaction entity."""
        _, soft, _ = _split_req(entity)
        parts = [f"id={entity.id}", f"name=\"{entity.name}\"",
                 f"trigger=\"{entity.trigger}\""]
        if soft:
            parts.append(f"条件=\"{soft}\"")
        return f"  {prefix} " + " ".join(parts)

    def _fmt_at(entity, prefix: str = "[AUTO_TRIGGER]") -> str:
        """Format an auto-trigger entity."""
        _, soft, _ = _split_req(entity)
        parts = [f"id={entity.id}", f"name=\"{entity.name}\""]
        if soft:
            parts.append(f"条件=\"{soft}\"")
        return f"  {prefix} " + " ".join(parts)

    completed_scene: list[str] = []
    completed_npc: list[str] = []

    if node:
        for at in node.auto_triggers:
            _, _, met = _split_req(at)
            line = _fmt_at(at, "[AUTO_TRIGGER]")
            if world.is_entity_completed(at.id):
                completed_scene.append(line)
            elif met:
                trig_scene.append(line)
            else:
                nontrig_scene.append(line)
        for inter in node.interactions:
            _, _, met = _split_req(inter)
            line = _fmt_inter(inter, "[INTERACT]")
            if world.is_entity_completed(inter.id):
                completed_scene.append(line)
            elif met:
                trig_scene.append(line)
            else:
                nontrig_scene.append(line)

    # ── Dynamic NPC entities: resolved from NPC profiles based on NPC's current scene ──
    if hasattr(world, 'npcs') and world.npcs:
        from scenario_core import Entity, parse_hard_requirement as _phr

        def _parse_req(req_str: str):
            """Parse requirement string into (hard_met, soft_display)."""
            if not req_str.strip():
                return True, ""
            if "||" in req_str:
                hard, soft = req_str.split("||", 1)
                hard, soft = hard.strip(), soft.strip()
            else:
                hard, soft = req_str.strip(), ""
            if not hard:
                return True, soft
            met = _phr(hard, world.runtime_state)
            return met, soft

        def _split_req_str(req_str: str, w):
            """Parse requirement string into (hard, soft, met)."""
            if not req_str.strip():
                return "", "", True
            if "||" in req_str:
                hard, soft = req_str.split("||", 1)
                hard, soft = hard.strip(), soft.strip()
            else:
                hard, soft = req_str.strip(), ""
            met = True
            if hard:
                met = _phr(hard, w.runtime_state)
            return hard, soft, met
        for npc in world.npcs._npcs.values():
            if npc.scene != world.current_location:
                continue
            if npc.state in ("dead", "left"):
                continue
            # Bound interactions
            for ent in npc.bound_interactions:
                eid = ent.get("id", "")
                if not eid or world.is_entity_completed(eid):
                    continue
                req = ent.get("requirement", "") or ""
                met, soft = _parse_req(req)
                e = Entity.from_dict(ent, overrides={
                    "entity_type": "interaction",
                    "scene": ent.get("source_scene", ""),
                })
                line = _fmt_inter(e, "[NPC_INTERACT]")
                if met:
                    trig_npc.append(line)
                else:
                    nontrig_npc.append(line)
            # Bound auto_triggers
            for at in npc.bound_auto_triggers:
                eid = at.get("id", "")
                if not eid or world.is_entity_completed(eid):
                    continue
                req = at.get("requirement", "") or ""
                hard, soft, met = _split_req_str(req, world)
                e = Entity.from_dict(at, overrides={
                    "entity_type": "auto_trigger",
                    "scene": at.get("source_scene", ""),
                })
                line = _fmt_at(e, "[NPC_AT]")
                if met:
                    trig_npc.append(line)
                else:
                    nontrig_npc.append(line)

    trig_events = []
    nontrig_events = []
    for ev in world.graph.events.values():
        triggered = world.is_event_triggered(ev.id)
        if triggered:
            continue
        parts = [f"id={ev.id}", f"name=\"{ev.name}\"",
                 f"trigger=\"{ev.trigger}\""]
        hard, soft, met = _split_req(ev)
        if soft:
            parts.append(f"条件=\"{soft}\"")
        line = "  [EVENT] " + " ".join(parts)
        if hard:
            overall_met = met
        else:
            overall_met = True
        if overall_met:
            trig_events.append(line)
        else:
            nontrig_events.append(line)

    return trig_scene, nontrig_scene, trig_npc, nontrig_npc, trig_events, nontrig_events, completed_scene, completed_npc


def build_keeper_parse_prompt(world, user_input: str) -> str:
    """Keeper step 1: match player input against ALL entities, evaluate NL requirements."""
    snap = world.build_snapshot()
    scene_ctx = _build_scene_context(snap)
    state = _build_world_state(snap)
    context = world.memory.get_context()
    inv_info = _build_investigator_info(snap)
    player_state = _build_player_state(snap)
    scene_state = _build_scene_state(snap)
    time_block = _build_time_block(snap)

    (trig_scene, nontrig_scene, trig_npc, nontrig_npc,
     trig_events, nontrig_events, completed_scene, completed_npc) = _build_entity_lines(world)

    scene_entity_parts = []
    if trig_scene:
        scene_entity_parts.append("【可触发 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(trig_scene))
    if SHOW_NON_TRIGGERABLE and nontrig_scene:
        scene_entity_parts.append("【暂不可触发 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(nontrig_scene))
    if SHOW_COMPLETED and completed_scene:
        scene_entity_parts.append("【已完成 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(completed_scene))
    scene_entity_text = "\n\n".join(scene_entity_parts) if scene_entity_parts else "（无）"

    npc_entity_parts = []
    if trig_npc:
        npc_entity_parts.append("【可触发 — NPC 专属】\n" + "\n".join(trig_npc))
    if SHOW_NON_TRIGGERABLE and nontrig_npc:
        npc_entity_parts.append("【暂不可触发 — NPC 专属】\n" + "\n".join(nontrig_npc))
    if SHOW_COMPLETED and completed_npc:
        npc_entity_parts.append("【已完成 — NPC 专属】\n" + "\n".join(completed_npc))
    npc_entity_text = "\n\n".join(npc_entity_parts) if npc_entity_parts else ""

    event_parts = []
    if trig_events:
        event_parts.append("【可触发 — EVENT】\n" + "\n".join(trig_events))
    if SHOW_NON_TRIGGERABLE and nontrig_events:
        event_parts.append("【暂不可触发 — EVENT】\n" + "\n".join(nontrig_events))
    event_text = "\n\n".join(event_parts) if event_parts else "（无）"

    prompt = f"""
你的任务是为玩家的输入匹配结构化的内容

【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

{inv_info}
{player_state}
{scene_state}
{scene_ctx}
{time_block}
【场景实体】
{scene_entity_text}

{"【NPC 专属实体】\n" + npc_entity_text if npc_entity_text else ""}
【全局事件】
{event_text}

【玩家输入】
{user_input}

返回 JSON（直接输出，不要额外文字）：
{{
  "actions": [
    {{"type": "auto_trigger", "id": "AT1"}},
    {{"type": "interaction", "id": "I3"}},
    {{"type": "event", "id": "E22"}},
    {{"type": "move", "target": "7号车厢"}},
    {{"type": "search"}},
    {{"type": "other", "text": "唱了一首歌"}}
  ]
}}
"""
    _show_prompt("Keeper Parse", prompt, system="你是一个优秀的跑团KP，擅长理解玩家的意图并将之与游戏实体精准匹配。\n\n你的任务是为玩家输入匹配结构化的游戏内容。\n实体分为四类：[INTERACT]（场景交互）、[AUTO_TRIGGER]（自动触发）、[NPC_INTERACT]/[NPC_AT]（NPC 专属实体）、[EVENT]（全局事件）。\n硬性条件已由系统判定，你只需判断意图匹配了哪个可触发实体或行为(move/search/other/npc_interact)。\n只考虑可触发的entity，包括场景实体、NPC 专属实体和全局事件。\n如有「条件=」字段则需评估是否满足；无「条件=」字段则默认条件已满足。\n\n行为优先级：\n- 有明确对应实体时优先返回实体\n- 玩家行为泛指搜索整个场景时返回 search，玩家想要明确移动到另一个场景时返回 move\n- 当玩家明显是要和当前场景中存在的 NPC 对话/互动/询问/请求帮助时，返回 npc_interact，npc_name 填 NPC 名称\n- 其他情况下返回 other\n- 一般一个动作只匹配一个结果，特殊情况下允许多个。玩家一轮输入可能不只有一个动作，动作应该按照常识理解\n- auto_trigger 必须在 actions 列表最前面\n\n输出规则：id 必须从实体列表中精确复制；move.target 填可移动方向中列出的目标；只考虑可触发的entity。\n直接输出 JSON，不要额外文字。\n\n输出格式：{\"actions\": [{\"type\": \"auto_trigger\", \"id\": \"...\"}, ..., {\"type\": \"npc_interact\", \"npc_name\": \"NPC名称\"}]}")
    return prompt


# ── Keeper: Enrich (Step 3) ──

_STRIP_MARKUP_RE = re.compile(
    r'\s*@(spawn_enemy|grant_weapon|stat_change|item_gain|consume_item|npc_state_change|npc_follow)'
    r'\([^)]*\)'
)

def build_keeper_enrich_prompt(world, judged_entities, user_input) -> str:
    """Keeper step 3: describe and enrich entity results. No trigger evaluation."""
    snap = world.build_snapshot()
    state = _build_world_state(snap)
    scene_state = _build_scene_state(snap)
    time_block = _build_time_block(snap)

    entities_text = ""
    for e in judged_entities:
        # Strip @markup from result — the LLM doesn't need to see side effects
        clean_result = _STRIP_MARKUP_RE.sub("", e['result']).strip()
        entities_text += (
            f"  [{e['entity_type']}] id={e['id']} name=\"{e['name']}\" "
            f"result=\"{clean_result}\" success={e['success']}"
        )
        if e.get('skill_tier'):
            entities_text += f" skill_tier={e['skill_tier']}"
        entities_text += "\n"

    prompt = f"""
你的任务是整合不同的文本并以半结构化的json格式输出他们
【世界状态】
{state}

【当前场景】{snap['location']}
{snap['description']}

{scene_state}
{time_block}
【玩家输入】{user_input}

【本轮已触发实体】
{entities_text or '（无）'}

请为以上已触发实体做叙事整合。返回 JSON：
{{
  "results": "本轮所有实体结果合并润色后的连贯叙事",
  "reasoning": "简短说明整合逻辑",
  "emphasis_hint": "叙事强调方向"
}}

直接输出 JSON。
"""
    _show_prompt("Keeper Enrich", prompt, system="你是一个优秀的跑团KP，擅长叙事整合和氛围营造。\n\n你的任务是整合本轮所有已触发实体的结果，合并润色为统一连贯的叙事。\n\n叙事规则：\n- success=true → 结果清晰明确地整合，玩家能感知发生了什么\n- success=false → 若 result 已含明确失败后果（扣血/惩罚/敌人出现），直接保留原文整合，不得改为晦涩模糊；仅当 result 为简单「检定失败」类通用文字时才描述为晦涩、模糊、似错觉或微不足道的细节\n- 提供 reasoning 简短说明整合逻辑\n\n输出格式：{\"results\": \"合并叙事\", \"reasoning\": \"整合逻辑\", \"emphasis_hint\": \"叙事方向\"}。直接输出 JSON。")
    return prompt


# ── Narrator prompt ──

def build_narrator_prompt(brief, l1_scene=None, snap: dict | None = None, user_input: str = "") -> str:
    """Narrator: converts NarratorBrief + L1 context into immersive narrative."""
    entity_outcomes = ""
    flavor_outcomes = ""
    for o in brief.action_outcomes:
        if o.intent.action == "other" and o.entity_type != "auto_trigger":
            flavor_outcomes += f"  · {o.message}\n"
        elif o.entity_type != "auto_trigger":
            entity_outcomes += f"  {'✓' if o.success else '✗'} {o.message}\n"

    ambient_text = "\n".join(f"  · {a}" for a in brief.ambient_changes) or "（无）"

    l1_ctx = _build_l1l3_context(l1_scene=l1_scene,
                                  scene_name=brief.scene_snapshot.location)

    inv_info = _build_investigator_info(snap) if snap else ""

    prompt = f"""{l1_ctx}

{inv_info}
【玩家输入】{user_input or '（无）'}

【当前场景】{brief.scene_snapshot.location}
{brief.scene_snapshot.description}

【可通行方向】{', '.join(f"{e['target']}({e['method']})" for e in brief.scene_snapshot.exits)}

【实体行动结果】
{entity_outcomes or '（无）'}
{'' if not flavor_outcomes else f'【即兴行为】\n{flavor_outcomes}'}
【环境变化】
{ambient_text}

【叙事强调】{brief.suggested_emphasis}

请以TRPG主持人身份生成沉浸式叙事。

返回 JSON：
{{
  "brief": "简洁、清晰、客观的概括——本轮发生了什么。仅陈述事实，不含情绪色彩。",
  "narrative": "基于结果进行文学性展开，融入场景氛围，让玩家身临其境。中文不超过100字。",
  "scene_update": "当本轮行动导致场景发生持久可见变化时，输出变化后的完整场景描述（如物品被移走、门被打开、血迹出现、光源变化、NPC出现或离开、敌人被击败后留下尸体或痕迹）。无变化时填空字符串。"
}}

规则：
- 仅以【实体行动结果】和【场景感知信息】为依据回复用户的输入，严禁出现其他实质性内容
- 【场景感知信息】构成当前场景的完整感知背景，必须一并融入叙事
- 「即兴行为」仅为叙述性描写，不对世界产生任何实际影响，一带而过即可
- 直接输出 JSON。
"""
    _show_prompt("Narrator", prompt, system="你是一个优秀的跑团KP，擅长生动、沉浸的叙事。\n\n你的任务是结合实体行动结果和场景感知信息，为玩家本轮的行动生成沉浸式叙事。\n\n输出格式：{\"brief\": \"...\", \"narrative\": \"...\", \"scene_update\": \"\"}。直接输出 JSON。\n\n── 字段规则 ──\n- brief: 第三人称视角，简单清晰阐述本轮发生了什么。仅陈述事实，不含情绪色彩。不超过50字。\n- narrative: 第一人称视角（用「你」），以沉浸式语言描述玩家主观感受和经历。融入场景氛围。不超过100字。\n- scene_update: 当本轮行动导致场景发生持久可见变化时输出完整描述。无变化时为空。")
    return prompt


# ── Pre-parse disambiguator prompt ──

def build_pre_parse_prompt(
    player_text: str,
    ambiguity_context: str = "",
    world_brief: str = "",
) -> str:
    """Pre-parse disambiguator: judge if player input is clear or ambiguous."""
    ctx_block = ""
    if ambiguity_context:
        ctx_block = f"【上一轮消歧上下文】\n{ambiguity_context}\n"

    world_block = ""
    if world_brief:
        world_block = f"【场景概览】\n{world_brief}\n"

    return f"""{ctx_block}{world_block}【玩家输入】{player_text}

判断这个输入是否足够清晰，可以直接交给KP解析执行。

消歧原则：一个清晰的行动需同时满足 动作 + 目标对象。缺少任一为模糊。
但注意这是多轮对话，目标可能来自前一轮或当前场景上下文。只要提出的目标有明确的指代性（示例："他"指代场景中或前文已出现的人物、"那里"指代前文提到的位置），即使 pre-parse 看不到具体指代内容，也视为清晰的引用目标。
- 指代不明："那个东西"（哪个？指代无锚点）、"这件事"（哪件事？前文未建立）→ ambiguous
- 缺目标："搜一下"（搜什么？）→ ambiguous
- 缺动作：仅提到对象名但无明确动作 → ambiguous
- 纯情绪/角色扮演（笑、哭、叹气、自言自语等）→ clear（RP 行为不需要动作+目标，直接执行即可）
- 搜索/观察环境整体（"搜索环境""观察四周""查看周围""环顾四周"等）→ clear（这是全局搜索动作，目标默认为当前场景环境）
- 有明确动作+目标或上下文隐含目标："检查抽屉""去5号车厢""和乘务员说话""跟他聊聊""继续搜"→ clear

跨轮整合：若提供上一轮消歧上下文，尝试将本轮输入与上轮模糊意图整合。若能整合为清晰意图 → clear。

返回 JSON：
{{
  "clarity": "clear" 或 "ambiguous",
  "interpretation": "一句话解读玩家意图",
  "resolved_text": "仅 clear 且存在跨轮上下文整合时填入——将上下文与本轮输入合并为完整清晰的行动描述。例如上文'搜一下'→本轮'抽屉'→整合为'搜查抽屉'。若无上下文整合则留空",
  "question": "仅 ambiguous 时填入。自然语言开放式反问，附带1-2个简短示例引导玩家回答。例如'搜查哪里？比如你可以说\\'检查抽屉\\'、\\'翻找柜子\\''"
}}

直接输出 JSON。"""
    _show_prompt("pre_parse", prompt)
    return prompt


# ── Author prompt ──

def _describe_value(obj, indent=0) -> str:
    """Convert any JSON-compatible value to natural language lines.
    Auto-adapts to field changes — no hardcoded keys."""
    prefix = "  " * indent
    if obj is None or obj == "" or obj == [] or obj == {}:
        return ""
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            desc = _describe_value(v, indent + 1)
            if desc:
                lines.append(f"{prefix}{k}:")
                lines.append(desc)
        return "\n".join(lines)
    if isinstance(obj, list):
        if all(isinstance(v, str) for v in obj):
            return f"{prefix}{', '.join(obj)}"
        lines = []
        for i, item in enumerate(obj):
            desc = _describe_value(item, indent + 1)
            if desc:
                label = _describe_label(item)
                lines.append(f"{prefix}{label}" if label else f"{prefix}-" + desc.lstrip())
        return "\n".join(lines)
    return f"{prefix}{obj}"


def _describe_label(item: dict) -> str:
    """Extract a short label from a dict (id+name), for list items like world_rules."""
    eid = item.get("id", "")
    name = item.get("name", "")
    if eid and name:
        return f"[{eid}] {name}"
    return eid or name or ""


def build_author_prompt(request, l3_data, persona: str = "") -> str:
    """Author: judges patch/structural level, generates content."""
    _get = lambda obj, key, default="": obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    # ── Persona ──
    persona_ctx = f"【创作者人设】{persona}" if persona else ""

    # ── L3 context (auto-adaptive via _describe_value) ──
    l3_parts = ["【L3模组设计】"]
    world_rules = _get(l3_data, "world_rules", [])
    if world_rules:
        l3_parts.append("  世界规则:")
        for wr in world_rules:
            l3_parts.append(f"    [{_get(wr,'id','')}] {_get(wr,'name','')}")
            l3_parts.append(f"      规则: {_get(wr,'rule','')}")
            l3_parts.append(f"      范围: {_get(wr,'scope','')}")
            l3_parts.append(f"      性质: {_get(wr,'is_absolute','')}")

    driving_force = _get(l3_data, "driving_force", "")
    if driving_force:
        l3_parts.append(f"  核心驱动力: {driving_force}")

    narrative_lines = _get(l3_data, "narrative_lines", [])
    if narrative_lines:
        l3_parts.append("  叙事线:")
        for nl in narrative_lines:
            nl_type = _get(nl, "type", "main")
            nl_name = _get(nl, "name", "")
            nl_outline = _get(nl, "outline", "")
            nl_scenes = _get(nl, "key_scenes", [])
            type_label = {"main": "主线", "branch": "支线", "optional": "可选支线"}.get(nl_type, nl_type)
            l3_parts.append(f"    [{type_label}] {nl_name}")
            if nl_outline:
                l3_parts.append(f"      大纲: {nl_outline}")
            if nl_scenes:
                l3_parts.append(f"      关键场景: {', '.join(nl_scenes)}")

    tc = _get(l3_data, "tone_constraints", {})
    if tc:
        tc_desc = _describe_value(tc, indent=1)
        if tc_desc:
            l3_parts.append("  基调约束:")
            l3_parts.append(tc_desc)

    scene_intents = _get(l3_data, "scene_intents", {})
    current_scene = request.scene_context.get("location", "")
    current_intent = scene_intents.get(current_scene, {}) if isinstance(scene_intents, dict) else {}
    if current_intent:
        si_desc = _describe_value(current_intent, indent=1)
        if si_desc:
            l3_parts.append("  当前场景设计意图:")
            l3_parts.append(si_desc)

    l3_ctx = "\n".join(l3_parts)

    # ── Scene context (natural language) ──
    scene_parts = ["【当前场景】"]
    sc = request.scene_context
    location = sc.get("location", "")
    description = sc.get("description", "")
    available = sc.get("available_scenes", [])
    npc_states = sc.get("npc_states", {})
    runtime = sc.get("runtime_summary", {})
    if location:
        scene_parts.append(f"  位置: {location}")
    if description:
        scene_parts.append(f"  描述: {description}")
    if available:
        scene_parts.append(f"  可用场景: {', '.join(available)}")
    if npc_states:
        scene_parts.append(f"  NPC:")
        scene_parts.append(_describe_value(npc_states, indent=2))
    if runtime:
        scene_parts.append(f"  已完成交互:")
        scene_parts.append(_describe_value(runtime, indent=2))
    scene_ctx = "\n".join(scene_parts)

    # ── Player intent ──
    intent_ctx = f"""【玩家意图】
  玩家想做什么: {request.intent}
  升级原因: {request.reasoning}
  玩家原话: {'; '.join(request.other_texts)}"""

    # ── WR0 ──
    wr0_enabled = sc.get("wr0_enabled", False)
    wr0_line = (
        "【WR0 创作者豁免】开启 — 你可选择突破世界规则进行结构性扩展（仅限 structural 级别）。"
        if wr0_enabled else
        "【WR0 状态】关闭 — 所有内容必须与既有世界规则、基调、L3设计意图保持一致。"
    )
    wr0_patch_rule = (
        "【WR0 对于 patch 级别】patch 始终不受 WR0 影响——patch 是模组缺口填充，必须遵循现有世界规则，不得引入违背规则的内容。"
        "若玩家意图违反世界规则且 WR0 关闭，应打回（entities=[]）；若 WR0 开启，仅 structural 级别可突破规则。"
    )

    prompt = f"""{l3_ctx}

{scene_ctx}

{intent_ctx}

{persona_ctx}

{wr0_line}
{wr0_patch_rule}

请评估此意图的范围并生成响应：

1. 判断级别：
   - patch：行为合理但模组未覆盖 → 在当前可用场景中添加 entity（patch 始终遵循世界规则，WR0 不影响 patch）
   - structural：行为完全超出模组范围，需要结构性扩展（新场景、新结局）。若 WR0 开启则可突破世界规则；若 WR0 关闭则必须与 L3 一致

2. 如果 patch：
   {{
     "level": "patch",
     "entities": [
       {{
         "id": "SI1",
         "entity_type": "interaction",
         "scene": "场景名",
         "name": "entity名称",
         "type": "关联技能名或留空",
         "requirement": "",
         "trigger": "触发描述",
         "result": "结果描述",
         "side_effects": [],
         "graded_result": null,
         "difficulty": "regular"
       }}
     ],
     "scene_descriptions": {{}},
     "justification": "L3层面理由"
   }}

3. 如果 structural（触发补充管线，生成新场景）：
   entry_scene 是玩家当前所在场景（新内容的入口），exit_scene 是希望玩家最终回流的场景（可留空由管线自行决定）。补充管线会以 entry/exit 为锚点生成新场景及通行路径。
   {{
     "level": "structural",
     "entry_scene": "玩家当前场景",
     "exit_scene": "出口场景名或空",
     "justification": "为什么需要结构性扩展，引用L3设计意图"
   }}

4. 如果玩家意图违反世界规则 → 打回（patch 级别始终如此；structural 仅在 WR0 关闭时打回）：
   {{
     "level": "patch",
     "entities": [],
     "scene_descriptions": {{}},
     "justification": "为什么拒绝。格式: REJECTED: 具体原因"
   }}

Entity 字段规则：
- id: 全局唯一，patch 用 SI1/SI2...，auto_trigger 用 SAT1/SAT2...，event 用 SE1/SE2...
- entity_type: interaction / auto_trigger / event
- scene: 所在场景名（中文）
- name: 简短动作名
- type: 关联技能名（如"侦查""急救"），不涉及检定填"无"
- requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 SI1 AND SI2、(SI1 OR SI2) AND SI3），裸 entity ID 默认指该实体成功完成。无条件填空字符串。需要特殊条件（如实体检定失败、调查员理智极度崩溃等）在 "||" 后用自然语言描述。requirement 可描述是否需要消耗常见物品及数量（如"需要消耗1个急救包"）
- trigger: 触发场景——描述什么情况下玩家可以执行此互动。不要和 requirement 混淆
- result: 直接结果——互动直接产生的可感知结果。如果会触发游戏结局，必须以 ##END_结局名称:结局简述## 开头。涉及技能检定时 result 填 "##GRADED##"（占位标记），side_effects 留空，所有结果文字写入 graded_result
- side_effects: 间接后果——与 result 不重合的附带影响。自然语言字符串列表。无条件则为空列表
- difficulty: None / regular / hard / extreme；不涉及检定则为 None
- graded_result: type 不为"无"时填写。四等级：on_failure=检定失败、on_regular=常规成功、on_hard=困难成功（≤技能值/2）、on_extreme=极难成功（≤技能值/5）。若原文未区分等级，各等级可描述相同内容
- entities 的 result/side_effects 不涉及进入与怪物的战斗/对抗/追捕（怪物遭遇和战斗由 game loop 运行时统一管理）。可以声明怪物出现，但不描述进入和怪物的对砍/战斗
- @标记可嵌入 result / side_effects / graded_result 任意字段中，与普通文本混合。间接/附带影响使用 @函数(参数) 语法：@spawn_enemy(enemy_ref="名称", scene="场景", quantity=1) / @grant_weapon(weapon_ref="名称", scene="场景", quantity=1) / @stat_change(stat_name="属性", delta=-1) / @item_gain(item_name="物品", quantity=1) / @consume_item(item_name="物品", quantity=1) / @npc_state_change(npc_name="名称", new_state="状态") / @npc_follow(npc_name="名称", follow=true). @grant_weapon 若 scene 为空，表示直接授予调查员（等价于搜索拾取武器的流程，只是触发条件不同）

创作规则：
- 只添加必要的entity，不要过度扩充
- structural 仅在玩家行为确实需要时才使用
- justification 必须引用L3设计意图
- 直接输出 JSON
"""
    _show_prompt("Author", prompt)
    return prompt


# ── Combat Entry + Standoff ──

def build_combat_entry_prompt(
    player_input: str,
    outcomes_summary: str,
    enemy_context: str,
    current_scene: str,
) -> str:
    prompt = f"""你是 COC 7th KP 助理。根据玩家行为、本轮结果和场景内敌人的习性，判断是否应进入回合制战斗。

玩家输入：{player_input}
本轮结果：{outcomes_summary}
当前位置：{current_scene}

场景内敌人：
{enemy_context}

请判断是否有敌人应进入战斗。输出 JSON：
{{"enter_combat": true/false, "reasoning": "简述判定理由"}}"""
    _show_prompt("Combat Entry", prompt)
    return prompt


def build_standoff_match_prompt(player_input: str) -> str:
    from utils import get_coc_skill_names
    skill_list = "、".join(get_coc_skill_names())
    prompt = f"""你是 COC 7th KP 助理。玩家在面对敌人时试图避免战斗。

玩家输入："{player_input}"

可用技能：{skill_list}

判断玩家意图对应的技能检定（如果有）：
{{"matched": true/false, "skill_name": "技能名", "reason": "简述为什么匹配"}}

规则：
- matched=false 表示玩家输入无法匹配为任何有意义的避免战斗的尝试（包括"什么都不做"、直接攻击等）
- 魅惑/取悦 → "魅惑"
- 说服/交涉/讲道理 → "说服"
- 潜行/偷偷溜走/绕过去 → "潜行"
- 恐吓/威胁 → "恐吓"
- 其他无法匹配的输出 matched=false"""
    _show_prompt("Standoff Match", prompt)
    return prompt


def build_combat_narrative_prompt(round_log: list, enemies_desc: str,
                                   player_name: str, scene: str) -> str:
    """Build prompt for per-round combat narrative generation."""
    log_text = ""
    for a in round_log:
        log_text += (
            f"  {'玩家' if a.actor == 'player' else a.actor} "
            f"{chr(10003) if a.success else chr(10007)} {a.weapon or a.action_type}: {a.narrative}\n"
        )

    prompt = f"""你是一个TRPG战斗叙事者。根据本轮的机械结果，生成一段沉浸式战斗描写。

【场景】{scene}
【调查员】{player_name}
【敌人】{enemies_desc}

【本轮行动】
{log_text}

返回 JSON：
{{"narrative": "沉浸式战斗描写（中文不超过80字）", "scene_hint": ""}}
直接输出 JSON。"""
    _show_prompt("Combat Narrative", prompt)
    return prompt


def build_stat_narrative_prompt(
    inv_desc: str,
    stat_name: str,
    delta: str,
    narrative: str,
) -> str:
    prompt = f"""你是 COC 7th KP 助理。调查员的一项属性发生了变化，请据此更新其个人描述。

当前描述：{inv_desc}

属性变化：{stat_name} {delta}
变化说明：{narrative}

请输出一个更新后的个人描述（150字以内），融合本次变化的影响。保持原有风格和内容，仅增量更新。
输出 JSON：{{"description": "更新后的描述文本"}}"""
    _show_prompt("Stat Narrative", prompt)
    return prompt


def build_consume_item_fuzzy_prompt(
    target: str,
    quantity: int,
    held_items: str,
) -> str:
    prompt = f"""你是 COC 7th KP 助理。玩家需要消耗一个物品，但物品名称与背包中的精确名称不匹配。请判断背包中是否有语义相同的物品。

目标物品：{target}（需要消耗 x{quantity}）
背包物品：
{held_items}

请判断背包中是否有物品与"{target}"语义相同：
{{"matched": true/false, "item_name": "背包中的实际物品名", "reason": "匹配理由"}}

规则：
- 模糊匹配（如"手电"匹配"手电筒"、"绷带"匹配"急救包"）→ matched=true
- 完全无关 → matched=false
- item_name 必须是背包中存在的物品名（精确复制）"""
    _show_prompt("Consume Item Fuzzy", prompt)
    return prompt


# ── Time Pressure ──

def build_time_pressure_assess_prompt(
    guide: str,
    urgency: int,
    urgency_max: int,
    key_signals: list,
    game_time: int,
    day: int,
    time_of_day: str,
    current_scene: str,
    player_actions: str,
    world_state: str,
) -> str:
    signals = "\n".join(f"- {s}" for s in key_signals)
    prompt = f"""你是 COC 7th 模组的时间压力管理者。根据模组预设的时间压力指南和当前游戏状态，判断是否需要介入催促玩家。

【时间压力指南】
{guide}

当前 urgency：{urgency}/{urgency_max}

可选信号：
{signals}

【当前状态】
累计时间：{game_time}分钟 (第{day}天 {time_of_day})
当前场景：{current_scene}
玩家最近行动：{player_actions}
世界状态：{world_state}

判断是否需要介入。返回 JSON：
{{"should_press": true/false, "urgency_update": 新的urgency值(0-{urgency_max})或null, "reason": "简要理由", "signal": "选用的信号文本（should_press=true时填写）"}}

规则：
- 玩家推进正常、无异常停留 → should_press=false
- 玩家反复搜索同一区域、长时间无进展、或 guide 中明确的时间节点被跨越 → should_press=true
- urgency_update 根据 guide 中的描述弹性调整，不机械"""
    _show_prompt("Time Pressure", prompt)
    return prompt


# ── NPC Intent Detection + NPC Parse ──

def build_npc_intent_detect_prompt(user_input: str, npc_names: list[str]) -> str:
    """Flash LLM: determine if player input is actually talking to an NPC."""
    names_text = "、".join(npc_names)
    prompt = f"""判断玩家输入是否真的是在和 NPC 对话。

在场景中的 NPC：{names_text}
玩家输入：「{user_input}」

判断标准：
- 如果玩家在对 NPC 说话/询问/请求，is_talking=true
- 如果玩家只是在描述场景/物品中提到了 NPC 名字（如"墙上写着老妇人三字"、"老妇人的照片"），is_talking=false
- 如果玩家同时有对话意图和实体操作意图，is_talking=true

返回 JSON：
{{"is_talking": true/false, "npc_name": "对话目标NPC名称或空"}}

直接输出 JSON。"""
    _show_prompt("NPC Intent Detect", prompt)
    return prompt


def build_npc_parse_prompt(npc_name: str, user_input: str, bound_interactions: list[dict],
                            bound_auto_triggers: list[dict], current_scene: str) -> str:
    """NPC turn: match player input against NPC's bound entities (current scene only)."""
    scene_entities = [e for e in bound_interactions
                      if e.get("source_scene", "") == current_scene]
    scene_at = [e for e in bound_auto_triggers
                if e.get("source_scene", "") == current_scene]

    entity_text = ""
    for e in scene_entities:
        entity_text += f"  [INTERACT] id={e.get('id','')} name=\"{e.get('name','')}\" trigger=\"{e.get('trigger','')}\"\n"
    for e in scene_at:
        entity_text += f"  [AUTO_TRIGGER] id={e.get('id','')} name=\"{e.get('name','')}\" trigger=\"{e.get('trigger','')}\"\n"

    prompt = f"""你是 NPC「{npc_name}」的互动解析助手。判断玩家输入是否触发了以下实体。

【NPC 专属实体】
{entity_text or '（无）'}

【玩家输入】
{user_input}

返回 JSON：
{{
  "matched_entities": ["entity_id_1", "entity_id_2"],
  "follow_request": true/false,
  "reasoning": "简短匹配逻辑"
}}

follow_request：如果玩家请求 NPC 跟随自己（"跟我来""跟我走""跟着我"等），设为 true。
直接输出 JSON。"""
    _show_prompt("NPC Parse", prompt)
    return prompt
