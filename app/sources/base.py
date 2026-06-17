"""Source abstraction.

Every way of getting holdings into the app implements `PortfolioSource.fetch()`
and returns normalized `Holding` objects. Adding E*TRADE/Robinhood APIs or Plaid
later means writing a new subclass — the DuckDB store and the dashboard never
need to change.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional

from app.models import ImportResult


class PortfolioSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self) -> ImportResult:
        """Return the source's accounts, holdings and balances, normalized."""
        raise NotImplementedError


def to_float(value, default: float = 0.0) -> float:
    """Parse a messy money/number string ('$1,234.50', '(12.30)', '62.77%') to float."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in {"n/a", "na", "--", "-"}:
        return default
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[,$%()]", "", s).strip()
    if not s:
        return default
    try:
        val = float(s)
    except ValueError:
        return default
    return -val if negative else val


def parse_date(value) -> Optional[str]:
    """Normalize a date string to ISO 'YYYY-MM-DD', or None if unparseable."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d-%b-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None
