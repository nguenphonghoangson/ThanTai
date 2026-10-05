"""Parser for the JSON-lines draw format.

One object per line::

    {"id": "00198", "date": "2017-10-25", "result": [12, 17, 23, 25, 34, 38]}

For games with a bonus ball the bonus is either the extra last element of
``result`` (the public dataset's convention) or an explicit ``"bonus"`` key.
"""
from __future__ import annotations

import json
from datetime import date
from typing import List

from app.data.errors import MalformedDataError
from app.data.normalize import NormalizeResult, normalize_draws
from app.domain.games import LotteryGameConfig
from app.domain.models import DrawResult, DrawValidationError, RejectedRecord


def parse_jsonl(game: LotteryGameConfig, text: str, source: str) -> NormalizeResult:
    draws: List[DrawResult] = []
    rejected: List[RejectedRecord] = []
    non_blank = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        non_blank += 1
        try:
            draws.append(_parse_record(game, json.loads(line)))
        except (ValueError, TypeError, KeyError, DrawValidationError) as exc:
            # json.JSONDecodeError and DrawValidationError are ValueError subclasses.
            rejected.append(RejectedRecord(f"line {lineno}", f"{type(exc).__name__}: {exc}"))

    if non_blank and not draws:
        raise MalformedDataError(
            f"{source}: none of {non_blank} records are valid {game.name} draws "
            f"(first error: {rejected[0].reason})"
        )
    result = normalize_draws(draws)
    result.rejected[:0] = rejected
    return result


def _parse_record(game: LotteryGameConfig, rec: dict) -> DrawResult:
    if not isinstance(rec, dict):
        raise TypeError("record is not an object")
    numbers = rec["result"]
    if not isinstance(numbers, list):
        raise TypeError("'result' is not a list")
    bonus = rec.get("bonus")
    if game.has_bonus_number and bonus is None:
        if len(numbers) != game.numbers_per_draw + 1:
            raise DrawValidationError(
                f"expected {game.numbers_per_draw} numbers + bonus, got {len(numbers)} values"
            )
        numbers, bonus = numbers[:-1], numbers[-1]
    raw_id = str(rec["id"]).strip()
    if not raw_id.isdigit():
        raise ValueError(f"draw id {raw_id!r} is not numeric")
    return DrawResult.create(
        game,
        draw_id=f"{int(raw_id):05d}",  # canonical zero-padded form, e.g. "00944"
        draw_date=date.fromisoformat(str(rec["date"])),
        numbers=numbers,
        bonus_number=bonus,
    )
