import json
from datetime import date

import pytest

from app.data.errors import MalformedDataError
from app.data.normalize import normalize_draws
from app.data.providers.jsonl_format import parse_jsonl
from app.domain.games import MEGA_645, POWER_655
from app.domain.models import DrawResult


def line(id_, d, result, **extra):
    return json.dumps({"id": id_, "date": d, "result": result, **extra})


def test_parses_mega_records_and_sorts_chronologically():
    text = "\n".join([
        line("00002", "2024-01-05", [41, 3, 23, 12, 31, 18]),
        "",
        line("00001", "2024-01-03", [1, 7, 9, 22, 33, 45]),
    ])
    result = parse_jsonl(MEGA_645, text, "t")
    assert [d.draw_id for d in result.draws] == ["00001", "00002"]
    assert result.draws[1].numbers == (3, 12, 18, 23, 31, 41)
    assert result.rejected == []


def test_power_bonus_is_last_value_or_explicit_key():
    text = "\n".join([
        line("1", "2024-01-02", [5, 10, 14, 23, 24, 38, 35]),
        line("2", "2024-01-04", [4, 9, 24, 25, 27, 45], bonus=40),
    ])
    a, b = parse_jsonl(POWER_655, text, "t").draws
    assert (a.draw_id, a.numbers, a.bonus_number) == ("00001", (5, 10, 14, 23, 24, 38), 35)
    assert (b.numbers, b.bonus_number) == ((4, 9, 24, 25, 27, 45), 40)


def test_power_record_without_bonus_rejected():
    text = "\n".join([
        line("1", "2024-01-02", [5, 10, 14, 23, 24, 38, 35]),
        line("2", "2024-01-04", [1, 12, 21, 28, 30, 44]),
    ])
    result = parse_jsonl(POWER_655, text, "t")
    assert [d.draw_id for d in result.draws] == ["00001"]
    assert "line 2" in result.rejected[0].ref and "bonus" in result.rejected[0].reason


@pytest.mark.parametrize("bad", [
    "{not json",
    json.dumps([1, 2, 3]),
    json.dumps({"id": "3", "date": "2024-01-07"}),                        # missing result
    line("3", "2024-13-40", [1, 2, 3, 4, 5, 6]),                          # bad date
    line("abc", "2024-01-07", [1, 2, 3, 4, 5, 6]),                        # non-numeric id
    line("3", "2024-01-07", [1, 2, 3, 4, 5, 46]),                         # out of range
    line("3", "2024-01-07", [1, 1, 3, 4, 5, 6]),                          # duplicate
    line("3", "2024-01-07", [1, 2, 3, 4, 5]),                             # wrong size
    line("3", "2024-01-07", "1,2,3,4,5,6"),                               # result not a list
])
def test_malformed_records_are_skipped(bad):
    text = "\n".join([line("1", "2024-01-03", [1, 2, 3, 4, 5, 6]), bad])
    result = parse_jsonl(MEGA_645, text, "t")
    assert len(result.draws) == 1
    assert len(result.rejected) == 1


def test_entirely_malformed_response_raises():
    with pytest.raises(MalformedDataError):
        parse_jsonl(MEGA_645, "<html><body>Just a moment...</body></html>", "t")


def test_empty_response_is_not_an_error():
    assert parse_jsonl(MEGA_645, "", "t").draws == []


def _d(id_, day, nums=(1, 2, 3, 4, 5, 6)):
    return DrawResult.create(MEGA_645, id_, date(2023, 10, day) if isinstance(day, int) else day, nums)


def test_normalize_drops_identical_duplicates_and_rejects_conflicts():
    a = _d("00001", 1)
    result = normalize_draws([a, a, _d("00001", 1, (7, 8, 9, 10, 11, 12))])
    assert result.draws == [a]
    assert [r.reason for r in result.rejected] == ["conflicting duplicate draw_id"]


def test_normalize_rejects_record_out_of_date_sequence():
    # Mirrors the real dataset error: draw 944 filed with a date a year earlier.
    draws = [_d("00942", 10), _d("00943", 12), _d("00944", date(2022, 9, 23)), _d("00945", 17), _d("00946", 19)]
    result = normalize_draws(draws)
    assert [d.draw_id for d in result.draws] == ["00942", "00943", "00945", "00946"]
    assert len(result.rejected) == 1 and result.rejected[0].ref == "00944"


def test_normalize_rejects_out_of_sequence_last_record():
    result = normalize_draws([_d("00001", 10), _d("00002", 12), _d("00003", 1)])
    assert [d.draw_id for d in result.draws] == ["00001", "00002"]
