"""Cost tracking for LLM API calls.

Enforces daily budget limits and records per-call cost history.
"""
from datetime import datetime, date
from typing import List
from dataclasses import dataclass, field


@dataclass
class CostEntry:
    amount_usd: float
    timestamp: datetime = field(default_factory=datetime.now)
    model: str = ""


class CostTracker:
    """Tracks LLM API costs with daily budget enforcement."""

    def __init__(self, daily_limit: float = 5.0):
        self._daily_limit = daily_limit
        self._entries: List[CostEntry] = []

    @property
    def total_today(self) -> float:
        today = date.today()
        return sum(e.amount_usd for e in self._entries if e.timestamp.date() == today)

    @property
    def remaining_today(self) -> float:
        return max(0, self._daily_limit - self.total_today)

    @property
    def total_all_time(self) -> float:
        return sum(e.amount_usd for e in self._entries)

    def can_spend(self, amount: float = 0.01) -> bool:
        """Check if we can spend the given amount within today's budget."""
        return self.remaining_today >= amount

    def record(self, amount: float, model: str = ""):
        """Record a cost entry."""
        self._entries.append(CostEntry(amount_usd=amount, model=model))

    def get_daily_summary(self) -> dict:
        today = date.today()
        today_entries = [e for e in self._entries if e.timestamp.date() == today]
        return {
            "date": str(today),
            "total_usd": round(sum(e.amount_usd for e in today_entries), 6),
            "calls": len(today_entries),
            "budget_usd": self._daily_limit,
            "remaining_usd": round(self.remaining_today, 6),
            "all_time_usd": round(self.total_all_time, 6),
        }
