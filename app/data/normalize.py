"""Turn raw provider records into a clean, chronological draw list."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Sequence

from app.domain.models import DrawResult, RejectedRecord
from app.logging_config import log_event

logger = logging.getLogger(__name__)


@dataclass
class NormalizeResult:
    draws: List[DrawResult]
    rejected: List[RejectedRecord] = field(default_factory=list)


def draw_number(draw_id: str) -> int:
    """Numeric draw sequence. Vietlott ids are zero-padded integers ("00944")."""
    return int(draw_id)


def normalize_draws(draws: Iterable[DrawResult]) -> NormalizeResult:
    """Deduplicate, drop records that break draw-id/date ordering, sort chronologically.

    Draw ids are sequential and dates strictly increase with them. A record whose date
    falls outside its neighbours' dates is a data error (e.g. a row filed under the wrong
    id) and is rejected rather than silently trusted.
    """
    rejected: List[RejectedRecord] = []
    by_id = {}
    for d in draws:
        prev = by_id.get(d.draw_id)
        if prev is None:
            by_id[d.draw_id] = d
        elif prev != d:
            rejected.append(RejectedRecord(d.draw_id, "conflicting duplicate draw_id"))
        # identical duplicates are dropped silently

    ordered = sorted(by_id.values(), key=lambda d: draw_number(d.draw_id))
    kept = _drop_chronology_outliers(ordered, rejected)
    kept.sort(key=lambda d: (d.draw_date, draw_number(d.draw_id)))

    if rejected:
        log_event(logger, "normalize.rejected", logging.WARNING, count=len(rejected),
                  sample=[f"{r.ref}: {r.reason}" for r in rejected[:5]])
    return NormalizeResult(kept, rejected)


def _drop_chronology_outliers(ordered: Sequence[DrawResult], rejected: List[RejectedRecord]) -> List[DrawResult]:
    n = len(ordered)
    keep: List[DrawResult] = []
    for i, d in enumerate(ordered):
        lo = ordered[i - 1].draw_date if i > 0 else date.min
        hi = ordered[i + 1].draw_date if i < n - 1 else date.max
        if lo < d.draw_date < hi:
            keep.append(d)
        elif lo < hi:
            # Neighbours agree with each other, so this record is the odd one out.
            rejected.append(RejectedRecord(d.draw_id, f"date {d.draw_date} out of sequence"))
        else:
            keep.append(d)  # ambiguous: a neighbour is the outlier and will be caught on its own turn
    return keep
