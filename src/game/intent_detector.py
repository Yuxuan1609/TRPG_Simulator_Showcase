"""IntentDetector — lightweight LLM check for meaningful 'other' player input."""
from __future__ import annotations
import json

from llm import call_deepseek
from config_llm import LLM_FLASH_MODEL, RE_INTENT_DETECTOR
from .messages import IntentResult


class IntentDetector:
    """Lightweight LLM detector: does an 'other' action carry real narrative intent?

    Runs in parallel with Enrich when Parse returns 'other' entries.
    Uses flash model with minimal prompt for fast yes/no + one-line description.
    """

    def __init__(self):
        from monitor.agent_monitor import AgentMonitor
        from monitor.policies import IntentDetectorPolicy
        from llm import _init_sensor
        self.monitor = AgentMonitor("IntentDetector", _init_sensor(), IntentDetectorPolicy())

    def detect(self, other_text: str, world_snapshot: dict) -> IntentResult:
        """Judge whether 'other' text warrants Author attention."""
        if not other_text or not other_text.strip():
            return IntentResult(needs_author=False)

        if self.monitor.degraded:
            return IntentResult(needs_author=True,
                              intent="降级默认", reasoning="系统降级，默认触发 Author")

        prompt = self._build_prompt(other_text, world_snapshot)
        response = self.monitor.call(
            lambda p, **kw: call_deepseek(p, **kw),
            prompt, json_mode=True, model=LLM_FLASH_MODEL,
            reasoning_effort=RE_INTENT_DETECTOR,
            system="你是一个TRPG游戏状态监控者。判断玩家输入是否有值得KP关注的叙事意图。",
            fallback_schema={"has_intent": False, "intent": "", "reasoning": ""},
        )
        data = json.loads(response) if isinstance(response, str) else response
        return IntentResult(
            needs_author=data.get("has_intent", False),
            intent=data.get("intent", ""),
            reasoning=data.get("reasoning", ""),
        )

    def _build_prompt(self, other_text: str, world_snapshot: dict) -> str:
        return f"""判断以下玩家行为是纯角色扮演/情绪表达，还是有实际叙事意图（玩家想对游戏世界产生改变）。

【当前位置】{world_snapshot.get('location', '')}
【NPC状态】{json.dumps(world_snapshot.get('npc_states', {}), ensure_ascii=False)}

【玩家行为】{other_text}

纯角色扮演的例子：唱歌、讲笑话、自言自语、情绪表达、无目标的小动作。
有叙事意图的例子：试图与NPC/怪物交流、破坏场景物品、使用模组未提及的道具、开辟新的行动路径、**在场景中主动搜索/寻找合理存在的物品（如"找灭火器""翻储物柜""检查抽屉"等，即玩家试图发现模组未明确列出的场景中可能存在之物）**

返回 JSON：
{{
  "has_intent": true/false,
  "intent": "如有意图，一句话描述玩家想达成什么",
  "reasoning": "如有意图，为什么这需要创作者介入而非正常KP裁决"
}}

直接输出 JSON。"""
