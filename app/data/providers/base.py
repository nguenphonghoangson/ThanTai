from __future__ import annotations

from datetime import date
from typing import List, Sequence

from app.domain.models import DrawResult


def filter_range(draws: Sequence[DrawResult], start: date, end: date) -> List[DrawResult]:
    return [d for d in draws if start <= d.draw_date <= end]
