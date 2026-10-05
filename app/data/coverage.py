"""Inclusive date-interval arithmetic used for incremental fetching."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Tuple

DateRange = Tuple[date, date]  # inclusive on both ends

ONE_DAY = timedelta(days=1)


def merge_ranges(ranges: Iterable[DateRange]) -> List[DateRange]:
    """Merge overlapping or adjacent ranges into a sorted, disjoint list."""
    merged: List[DateRange] = []
    for start, end in sorted(r for r in ranges if r[0] <= r[1]):
        if merged and start <= merged[-1][1] + ONE_DAY:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def missing_ranges(requested: DateRange, covered: Iterable[DateRange]) -> List[DateRange]:
    """Parts of ``requested`` not inside any covered range."""
    start, end = requested
    gaps: List[DateRange] = []
    cursor = start
    for c_start, c_end in merge_ranges(covered):
        if c_end < cursor:
            continue
        if c_start > end:
            break
        if c_start > cursor:
            gaps.append((cursor, c_start - ONE_DAY))
        cursor = max(cursor, c_end + ONE_DAY)
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps
