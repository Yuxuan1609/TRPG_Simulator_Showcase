"""Pre-parse disambiguator — lightweight flash-model check before Parse.

Runs in parallel with Parse. When the player input is ambiguous (missing
action or target), blocks execution and returns a clarifying question instead.
Maintains cross-turn context to integrate follow-up responses.
"""
from __future__ import annotations
import json

from llm import call_deepseek
from config_llm import LLM_FLASH_MODEL
from .messages import PreParseResult

MAX_CONSECUTIVE_AMBIGUOUS = 2


class PreParseDisambiguator:
    """Lightweight pre-parse check. Runs in parallel with Keeper parse.

    Two-path output:
    - clear: Parse result proceeds normally (zero additional latency)
    - ambiguous: execution blocked, question shown to player

    Cross-turn context: when ambiguous, caches interpretation + question.
    Next turn's input is integrated with the cached context.
    """

    def __init__(self):
        self._context: str = ""  # cached interpretation + question from last ambiguous
        self._consecutive: int = 0

    def disambiguate(self, player_text: str, world_brief: str = "") -> PreParseResult:
        """Judge clarity of player input. Maintains cross-turn context.

        Args:
            player_text: raw player input for this turn
            world_brief: lightweight scene context (≤200 tokens)
        """
        from prompts import build_pre_parse_prompt

        # Force clear after consecutive ambiguous limit (deadlock guard)
        if self._consecutive >= MAX_CONSECUTIVE_AMBIGUOUS:
            self._context = ""
            self._consecutive = 0
            return PreParseResult(
                clarity="clear",
                interpretation=f"连续{MAX_CONSECUTIVE_AMBIGUOUS}次模糊输入，按字面执行：{player_text}",
                resolved_text="",
            )

        prompt = build_pre_parse_prompt(
            player_text=player_text,
            ambiguity_context=self._context,
            world_brief=world_brief,
        )
        try:
            response = call_deepseek(
                prompt, json_mode=True, model=LLM_FLASH_MODEL,
                thinking=False, _label="pre_parse",
                system="你是一个TRPG KP助理，擅长判断玩家输入是否清晰明确。你的唯一任务是消歧——判断输入是否需要进一步澄清，需要时生成引导性反问。",
                fallback_schema={
                    "clarity": "clear",
                    "interpretation": "",
                    "question": "",
                    "resolved_text": "",
                },
            )
        except Exception:
            return PreParseResult(clarity="clear", interpretation="消歧失败，默认执行")

        data = json.loads(response) if isinstance(response, str) else response
        clarity = data.get("clarity", "clear")

        if clarity == "ambiguous":
            self._consecutive += 1
            self._context = (
                f"上一轮模糊输入意图: {data.get('interpretation', '')}。"
                f"已反问: {data.get('question', '')}"
            )
        else:
            self._context = ""
            self._consecutive = 0

        return PreParseResult(
            clarity=clarity,
            interpretation=data.get("interpretation", ""),
            question=data.get("question", ""),
            resolved_text=data.get("resolved_text", ""),
        )
