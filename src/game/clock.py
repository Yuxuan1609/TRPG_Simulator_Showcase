"""GameClock — deterministic minute-clock. No LLM calls, no narrative logic."""
from __future__ import annotations


class GameClock:
    """Pure time tracker. Author handles narrative time pressure; TimeAgent handles
    per-action time assessment. The clock just counts."""

    def __init__(self, start_time: int = 0):
        self.game_time: int = start_time
        self.time_context: str = ""

    @property
    def day(self) -> int:
        return self.game_time // 1440

    @property
    def hour(self) -> int:
        return (self.game_time % 1440) // 60

    @property
    def time_of_day(self) -> str:
        h = self.hour
        if h < 5:
            return "夜间"
        if h < 8:
            return "早晨"
        if h < 17:
            return "白天"
        if h < 20:
            return "黄昏"
        return "夜间"

    def advance_time(self, minutes: int) -> None:
        self.game_time += minutes

    def get_time_flags(self) -> dict[str, bool]:
        return {
            f"day:{self.day}": True,
            f"time:{self.time_of_day}": True,
        }

    def to_dict(self) -> dict:
        return {
            "game_time": self.game_time,
            "game_time_minutes": self.game_time,
            "day": self.day,
            "hour": self.hour,
            "time_of_day": self.time_of_day,
            "time_context": self.time_context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameClock":
        clock = cls(start_time=data.get("game_time", 0))
        clock.time_context = data.get("time_context", "")
        return clock

    def __repr__(self) -> str:
        return f"GameClock(day={self.day}, {self.time_of_day} {self.hour}:00, total={self.game_time}m)"
