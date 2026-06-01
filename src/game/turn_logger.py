"""
TurnLogger — 每轮记录：玩家输入 + Enrich 输出 + Narrator 输出。

纯记录，不与其他代码交互。日志写入 data/debug/turn_logs/<timestamp>/turn_N.json
"""
from __future__ import annotations
import json, os
from datetime import datetime


class TurnLogger:
    """Per-turn recorder. Call log() at the end of each turn."""

    def __init__(self, log_dir: str = ""):
        if not log_dir:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            root = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "turn_logs")
            log_dir = os.path.join(root, ts)
        self.log_dir = os.path.normpath(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        self.turn_number = 0

    def log(self, player_input: str, enrich_result: dict | None,
            narrator_brief: str, narrator_narrative: str):
        """Record one turn. enrich_result may be None if enrich was skipped.

        Writes both a per-turn file (turn_NN.json) and appends to a merged
        log (turn_log.jsonl) with turn separation.
        """
        self.turn_number += 1
        entry = {
            "turn": self.turn_number,
            "player_input": player_input,
            "enrich": enrich_result,
            "narrator": {
                "brief": narrator_brief,
                "narrative": narrator_narrative,
            },
        }
        # Per-turn individual file
        path = os.path.join(self.log_dir, f"turn_{self.turn_number:02d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        # Merged log (JSONL: one JSON object per line)
        merged_path = os.path.join(self.log_dir, "turn_log.jsonl")
        with open(merged_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
