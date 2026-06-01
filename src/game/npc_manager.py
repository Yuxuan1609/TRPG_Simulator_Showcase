"""NPC dataclass + NPCManager — NPC 全量管理（对话/态度/跟随/状态）"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

from config import NPC_MEMORY_CAP


@dataclass
class NPC:
    name: str
    role: str = ""
    personality_notes: str = ""
    appearance: str = ""
    what_they_can_do: str = ""
    interaction_triggers: list[str] = field(default_factory=list)
    can_follow: bool = False
    follow_requirements: str = ""
    can_interact: bool = True
    interact_requirements: str = ""

    bound_interactions: list[dict] = field(default_factory=list)
    bound_auto_triggers: list[dict] = field(default_factory=list)

    scene: str = ""
    attitude: str = "neutral"
    following: bool = False
    memory: list[str] = field(default_factory=list)
    state: str = "alive"
    extra: dict | None = None


def _build_req_text(req_text: str, world) -> str:
    """Turn a requirement string into natural language with entity names.
    
    "E1&&E2||soft text" → "需要先完成「事件名1」和「事件名2」。软条件：soft text"
    "I1 AND I3" → "需要先完成「交互名1」和「交互名3」"
    """
    if not world or not req_text:
        return req_text
    id_to_name: dict[str, str] = {}
    try:
        for node in world.graph.nodes.values():
            for e in node.interactions:
                id_to_name[e.id] = e.name
            for e in node.auto_triggers:
                id_to_name[e.id] = e.name
        for eid, entity in world.graph.events.items():
            id_to_name[eid] = entity.name
        for npc in world.npcs._npcs.values():
            for e in npc.bound_interactions:
                id_to_name[e.get("id", "")] = e.get("name", e.get("id", ""))
            for e in npc.bound_auto_triggers:
                id_to_name[e.get("id", "")] = e.get("name", e.get("id", ""))
    except Exception:
        return req_text

    def _resolve(ids_text: str) -> str:
        result = ids_text
        for eid in sorted(id_to_name, key=len, reverse=True):
            if eid in result:
                result = result.replace(eid, f"「{id_to_name[eid]}」")
        for op in ("AND", "OR", "&&", "||"):
            result = result.replace(f" {op} ", "、").replace(f" {op}", "、").replace(f"{op} ", "、").replace(op, "、")
        while "  " in result:
            result = result.replace("  ", " ")
        return result.strip()

    if "||" in req_text:
        hard, soft = req_text.split("||", 1)
        hard, soft = hard.strip(), soft.strip()
    else:
        hard = req_text.strip()
        soft = ""

    hard_named = _resolve(hard)
    parts = []
    if hard_named:
        parts.append(f"需要先完成 {hard_named}")
    if soft:
        parts.append(f"软条件：{soft}")
    return "。".join(parts)


class NPCManager:
    def __init__(self):
        self._npcs: dict[str, NPC] = {}

    STATE_GATE_MESSAGES: dict[str, str] = {
        "dead": "（{name} 已无法交谈）",
        "left": "（{name} 不在此处）",
    }

    def _check_follow_conditions(self, npc: NPC, world) -> tuple[bool, str]:
        """Check if NPC can follow. Evaluates follow_requirements (|| split format).

        Hard part (before ||): entity IDs checked via parse_hard_requirement against runtime_state.
        Soft part (after ||): natural language — passed through (LLM evaluates at parse time).
        Also checks can_follow bool + state gate.
        """
        if not npc.can_follow:
            hint = ""
            if npc.follow_requirements and npc.follow_requirements.strip():
                resolved = _build_req_text(npc.follow_requirements.strip(), world)
                hint = f"，{resolved}"
            return False, f"{npc.name} 不愿意跟随你{hint}"
        if npc.state in ("dead", "left"):
            return False, f"{npc.name} 无法跟随（{npc.state}）"

        req = npc.follow_requirements.strip() if npc.follow_requirements else ""
        if not req:
            return True, ""

        # Split by ||
        if "||" in req:
            hard, soft = req.split("||", 1)
            hard, soft = hard.strip(), soft.strip()
        else:
            hard = req
            soft = ""

        if hard:
            from scenario_core import parse_hard_requirement
            if not parse_hard_requirement(hard, world.runtime_state):
                resolved = _build_req_text(hard + (f"||{soft}" if soft else ""), world)
                return False, f"尚未满足 {npc.name} 的跟随条件，{resolved}"
        return True, ""

    # ── 初始化 ──

    def init_from_profiles(self, profiles: dict):
        """从 L2 npc_profiles 批量创建 NPC 实例。"""
        for name, data in profiles.items():
            self._npcs[name] = NPC(
                name=data.get("name", name),
                role=data.get("role", ""),
                personality_notes=data.get("personality_notes", ""),
                appearance=data.get("appearance", ""),
                what_they_can_do=data.get("what_they_can_do", ""),
                interaction_triggers=list(data.get("interaction_triggers", [])),
                can_follow=data.get("can_follow", False),
                follow_requirements=data.get("follow_requirements", ""),
                can_interact=data.get("can_interact", True),
                interact_requirements=data.get("interact_requirements", ""),
                bound_interactions=list(data.get("bound_interactions", [])),
                bound_auto_triggers=list(data.get("bound_auto_triggers", [])),
                scene=data.get("scene", ""),
                state=data.get("initial_state", "alive"),
                following=data.get("initial_following", False),
                attitude=data.get("initial_attitude", "neutral"),
            )

    # ── 查询 ──

    def get(self, name: str) -> NPC | None:
        return self._npcs.get(name)

    def get_in_scene(self, scene: str) -> list[NPC]:
        return [n for n in self._npcs.values()
                if n.scene == scene and n.state not in ("dead", "left")]

    def get_in_scene_snapshot(self, scene: str) -> list[dict]:
        """Lightweight dict list for world snapshot — no dataclass internals exposed."""
        return [
            {"name": n.name, "state": n.state, "attitude": n.attitude, "following": n.following}
            for n in self._npcs.values()
            if n.scene == scene and n.state not in ("dead", "left")
        ]

    def all_names(self) -> list[str]:
        return list(self._npcs.keys())

    # ── 交互 ──

    def talk_to(self, npc_name: str, player_input: str, llm_call, world=None) -> str:
        """State gate -> can_interact gate -> interact_requirements gate -> inject profile/memory context -> LLM -> append memory.

        can_interact: NPC 是否具备互动能力（false = 永远不可自由对话，需 interact_unlock entity 解锁）。
        interact_requirements: 互动需满足的前置条件（|| 前硬性 entity ID，|| 后软性自然语言）。
        两者均满足时才能进行自由对话。
        """
        npc = self._npcs.get(npc_name)
        if not npc:
            return f"（{npc_name} 不在此处。）"

        gate = self.STATE_GATE_MESSAGES.get(npc.state, "")
        if gate:
            return gate.format(name=npc.name)

        if not npc.can_interact:
            hint = ""
            if npc.interact_requirements and npc.interact_requirements.strip():
                resolved = _build_req_text(npc.interact_requirements.strip(), world)
                hint = f"，{resolved}"
            return f"（{npc.name} 似乎不愿与你交谈{hint}。）"

        # Check interact_requirements (hard part evaluated against runtime_state)
        if npc.interact_requirements and npc.interact_requirements.strip():
            req = npc.interact_requirements.strip()
            if "||" in req:
                hard, soft = req.split("||", 1)
                hard, soft = hard.strip(), soft.strip()
            else:
                hard = req
                soft = ""
            if hard and world and hasattr(world, 'runtime_state'):
                from scenario_core import parse_hard_requirement
                if not parse_hard_requirement(hard, world.runtime_state):
                    resolved = _build_req_text(hard + (f"||{soft}" if soft else ""), world)
                    return f"（{npc.name} 暂时不愿与你交谈，{resolved}。）"

        triggers_text = ""
        if npc.interaction_triggers:
            triggers_text = f"互动触发条件：{'； '.join(npc.interaction_triggers)}\n"

        system_prompt = (
            f"你是 NPC「{npc.name}」。\n"
            f"角色：{npc.role}\n"
            f"性格：{npc.personality_notes}\n"
            f"外貌：{npc.appearance}\n"
            f"能力与所知信息：{npc.what_they_can_do}\n"
            + triggers_text
            + f"当前态度：{npc.attitude}\n"
            f"当前状态：{npc.state}\n"
            + (f"对话记忆：{'； '.join(npc.memory[-5:])}\n" if npc.memory else "")
            + "\n请用符合角色设定的语气回复调查员。\n"
            "若调查员询问或触及你能力范围内/互动触发条件中的信息，应如实告知所知内容，不刻意隐瞒。\n"
            "回复简洁（1-3句话）。"
        )
        user_prompt = f"调查员对你说：「{player_input}」"

        try:
            response = llm_call(user_prompt, system=system_prompt, json_mode=False)
        except Exception:
            response = f"（{npc.name} 沉默不语。）"

        npc.memory.append(f"玩家：「{player_input}」-> 回复：「{response}」")
        if len(npc.memory) > NPC_MEMORY_CAP:
            npc.memory = npc.memory[-NPC_MEMORY_CAP:]
        return response

    # ── 状态变更 ──

    def set_attitude(self, name: str, attitude: str):
        if name in self._npcs:
            self._npcs[name].attitude = attitude

    def set_following(self, name: str, following: bool):
        if name in self._npcs:
            self._npcs[name].following = following

    def get_following(self) -> list[NPC]:
        return [n for n in self._npcs.values() if n.following]

    def set_state(self, name: str, state: str):
        if name in self._npcs:
            self._npcs[name].state = state

    def set_scene(self, name: str, scene: str):
        if name in self._npcs:
            self._npcs[name].scene = scene

    # ── 跟随同步 ──

    def sync_followers(self, scene: str):
        """所有 following=True 的 NPC 自动移动到 scene。"""
        for npc in self._npcs.values():
            if npc.following:
                npc.scene = scene

    # ── 序列化 ──

    def to_dict(self) -> dict:
        result = {}
        for name, npc in self._npcs.items():
            entry = {
                "scene": npc.scene,
                "attitude": npc.attitude,
                "following": npc.following,
                "memory": list(npc.memory),
                "state": npc.state,
                "can_interact": npc.can_interact,
            }
            if npc.extra is not None:
                entry["extra"] = npc.extra
            result[name] = entry
        return result

    def from_dict(self, data: dict, profiles: dict):
        """从序列化数据恢复运行时状态。profiles 用于恢复档案字段。
        can_interact 优先使用运行时值（save 中可能已被 unlock），回退到 profile 静态值。"""
        for name, state_data in data.items():
            profile = profiles.get(name, {})
            self._npcs[name] = NPC(
                name=name,
                role=profile.get("role", ""),
                personality_notes=profile.get("personality_notes", ""),
                appearance=profile.get("appearance", ""),
                what_they_can_do=profile.get("what_they_can_do", ""),
                interaction_triggers=list(profile.get("interaction_triggers", [])),
                can_follow=profile.get("can_follow", False),
                follow_requirements=profile.get("follow_requirements", ""),
                can_interact=state_data.get("can_interact", profile.get("can_interact", True)),
                interact_requirements=profile.get("interact_requirements", ""),
                bound_interactions=list(profile.get("bound_interactions", [])),
                bound_auto_triggers=list(profile.get("bound_auto_triggers", [])),
                scene=state_data.get("scene", ""),
                attitude=state_data.get("attitude", "neutral"),
                following=state_data.get("following", False),
                memory=list(state_data.get("memory", [])),
                state=state_data.get("state", "alive"),
                extra=state_data.get("extra"),
            )

    def process_npc_turn(self, npc_name: str, user_input: str, world,
                         llm_json, llm_text, judge, curator) -> dict:
        """Execute NPC turn: talk_to -> parse -> judge -> enrich -> curate.
        Returns {'brief': NarratorBrief, 'npc_events': [...], 'enrich': str}.
        game_loop handles narration.
        """
        from prompts import build_npc_parse_prompt, build_keeper_enrich_prompt
        from game.messages import ActionIntent, ActionOutcome, EnrichInput
        from scenario_core import Entity as EntityCls

        npc = self._npcs.get(npc_name)
        if not npc:
            return {"brief": f"（{npc_name} 不在此处。）"}

        dialogue = self.talk_to(npc_name, user_input, llm_text, world=world)

        matched_entity_ids = []
        follow_request = False
        matched_entities = []

        if npc.bound_interactions or npc.bound_auto_triggers:
            parse_prompt = build_npc_parse_prompt(
                npc_name, user_input, npc.bound_interactions, npc.bound_auto_triggers,
                world.current_location,
            )
            try:
                parse_result = llm_json(parse_prompt)
                matched_entity_ids = parse_result.get("matched_entities", [])
                follow_request = parse_result.get("follow_request", False)
            except Exception:
                matched_entity_ids = []

            all_bound = npc.bound_interactions + npc.bound_auto_triggers
            for eid in matched_entity_ids:
                for e in all_bound:
                    if e.get("id") == eid:
                        matched_entities.append(e)
                        break

        npc_events = []
        if follow_request:
            ok, reason = self._check_follow_conditions(npc, world)
            if ok:
                self.set_following(npc_name, True)
                npc_events.append(f"{npc_name} 开始跟随你")
            else:
                npc_events.append(reason)

        all_outcomes: list[ActionOutcome] = []
        enrich_input = EnrichInput()
        for entity in matched_entities:
            ent = EntityCls.from_dict(entity, overrides={
                "scene": entity.get("source_scene", ""),
            })
            intent = ActionIntent(action="interact", target=entity.get("name", ""))
            outcome = judge._execute_entity(ent, intent=intent, player_input=user_input)
            all_outcomes.append(outcome)
            enrich_input.entities.append({
                "entity_type": ent.entity_type,
                "id": ent.id,
                "name": ent.name,
                "result": outcome.message,
                "success": outcome.success,
                "skill_tier": outcome.skill_tier,
            })
            if outcome.success:
                tr = entity.get("extra", {}).get("time_range") if entity.get("extra") else None
                enrich_input.actions.append({
                    "type": ent.entity_type,
                    "name": ent.name,
                    "success": True,
                    "time_range": tr,
                })

        enrich_prompt = build_keeper_enrich_prompt(world, enrich_input.entities, user_input)
        try:
            enrich_result = llm_json(enrich_prompt)
            enrich_text = enrich_result.get("results", dialogue)
            emphasis = enrich_result.get("emphasis_hint", "")
        except Exception:
            enrich_text = dialogue
            emphasis = ""

        if not all_outcomes:
            dialogue_outcome = ActionOutcome(
                intent=ActionIntent(action="other", target=npc_name),
                success=True, message=dialogue, entity_type="interaction",
            )
            all_outcomes = [dialogue_outcome]

        ambient_changes = [f"{npc_name}: {dialogue}"] if not matched_entities else []
        brief = curator.assemble(all_outcomes, ambient_changes, emphasis=emphasis)

        return {"brief": brief, "npc_events": npc_events, "enrich": enrich_text}

    def __repr__(self):
        return f"NPCManager({len(self._npcs)} NPCs)"
