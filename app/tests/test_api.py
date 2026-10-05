from datetime import date

from app.data.repository import SqliteDrawRepository
from app.database.sqlite import connect
from app.domain.games import MEGA_645
from app.domain.models import DrawResult

FETCH_BODY = {"game": "mega645", "start": "2024-01-01", "end": "2024-01-31"}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_games_endpoint(client):
    games = {g["key"]: g for g in client.get("/api/games").json()}
    assert games["mega645"]["low_range"] == [1, 22]
    assert games["power655"]["high_range"] == [28, 55]


def test_dashboard_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Vietlott Analyzer" in res.text
    assert "Power 6/55" in res.text
    for script in ("core.js", "analysis.js", "scoring.js", "generation.js", "backtest.js", "main.js"):
        assert client.get(f"/static/{script}").status_code == 200


def test_fetch_then_summary_and_draws(client):
    assert client.get("/api/data/summary?game=mega645").json()["total_draws"] == 0

    report = client.post("/api/data/fetch", json=FETCH_BODY).json()
    assert report["inserted"] == 3 and report["up_to_date"] is False

    s = client.get("/api/data/summary?game=mega645").json()
    assert s["total_draws"] == 3
    assert (s["first_date"], s["last_date"]) == ("2024-01-03", "2024-01-07")
    assert (s["first_draw_id"], s["last_draw_id"], s["missing_before_first"]) == ("00001", "00003", 0)
    assert s["missing_draw_count"] == 0
    # today is 2024-02-01 with 2 settle days, so coverage is recorded through 2024-01-30.
    assert s["covered_ranges"] == [["2024-01-01", "2024-01-30"]]

    draws = client.get("/api/data/draws?game=mega645&from=2024-01-04").json()
    assert [d["draw_id"] for d in draws] == ["00002", "00003"]


def test_second_fetch_only_requests_missing_range(client, fake_provider):
    client.post("/api/data/fetch", json=FETCH_BODY)
    fake_provider.calls.clear()
    report = client.post("/api/data/fetch", json=FETCH_BODY).json()
    # Only the unsettled day (today - 1) is re-checked.
    assert report["fetched_ranges"] == [["2024-01-31", "2024-01-31"]]
    assert [c[1:3] for c in fake_provider.calls] == [(date(2024, 1, 31), date(2024, 1, 31))]

    fake_provider.calls.clear()
    settled = client.post("/api/data/fetch", json={**FETCH_BODY, "end": "2024-01-30"}).json()
    assert settled["up_to_date"] is True and fake_provider.calls == []


def test_fetch_source_failure_returns_502(client, fake_provider):
    fake_provider.error = "network down"
    res = client.post("/api/data/fetch", json=FETCH_BODY)
    assert res.status_code == 502
    assert "network down" in res.json()["detail"]


def test_fetch_validation(client):
    assert client.post("/api/data/fetch", json={**FETCH_BODY, "game": "keno"}).status_code == 404
    assert client.post("/api/data/fetch", json={**FETCH_BODY, "start": "2024-02-01"}).status_code == 422


def test_unknown_game_404(client):
    assert client.get("/api/data/summary?game=keno").status_code == 404


def test_inverted_range_422(client):
    assert client.get("/api/data/draws?game=mega645&from=2025-01-01&to=2024-01-01").status_code == 422


def test_features_endpoint(client):
    assert client.get("/api/analysis/features?game=mega645").status_code == 422  # nothing stored yet
    client.post("/api/data/fetch", json=FETCH_BODY)
    res = client.get("/api/analysis/features?game=mega645&window=2&triples=true")
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["total_draws"] == 3
    assert body["summary"]["total_numbers"] == 18
    assert body["summary"]["average_odd"] + body["summary"]["average_even"] == 6
    f = body["features"]
    assert len(f["numbers"]) == 45 and f["config"]["hot_cold_window"] == 2
    assert f["triples"] is not None and f["pairs"] is not None
    assert "pair_matrix" not in f


def test_features_date_filter(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    body = client.get("/api/analysis/features?game=mega645&from=2024-01-04").json()
    assert body["summary"]["total_draws"] == 2


def test_scores_endpoint(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    body = client.get("/api/analysis/scores?game=mega645&strategy=balanced&window=2").json()
    assert len(body["scores"]) == 45 and body["customized"] is False
    first = body["scores"][0]
    assert {"number", "score", "rank", "components", "frequency", "recent", "gap"} <= set(first)
    assert body["params"]["scoring"]["strategy"] == "balanced"
    assert body["params"]["dataset_fingerprint"]


def test_scores_endpoint_overrides(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    body = client.get("/api/analysis/scores?game=mega645&strategy=balanced&w_pair=0&gap_mode=recency").json()
    assert body["customized"] is True
    assert body["params"]["scoring"]["weights"]["pair"] == 0
    assert body["params"]["scoring"]["weights"]["frequency"] == 0.30  # untouched preset value
    assert body["params"]["scoring"]["gap_mode"] == "recency"
    random_body = client.get("/api/analysis/scores?game=mega645&strategy=random").json()
    assert {s["score"] for s in random_body["scores"]} == {1.0}


def test_scores_endpoint_errors(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    assert client.get("/api/analysis/scores?game=mega645&strategy=ml").status_code == 404
    assert client.get("/api/analysis/scores?game=mega645&gap_mode=due").status_code == 422
    zero = "&".join(f"{k}=0" for k in ("w_frequency", "w_recent", "w_gap", "w_pair", "w_historical"))
    assert client.get(f"/api/analysis/scores?game=mega645&{zero}").status_code == 422
    assert client.get("/api/analysis/scores?game=power655").status_code == 422  # no data


def test_strategies_endpoint(client):
    keys = [s["key"] for s in client.get("/api/analysis/strategies").json()]
    assert keys == ["frequency", "recent", "balanced", "random"]


GEN_BODY = {"game": "mega645", "start": "2024-01-01", "end": "2024-01-31", "strategy": "balanced",
            "count": 5, "seed": 777, "window": 2}


def test_generate_and_session_endpoints(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    res = client.post("/api/generate", json=GEN_BODY)
    assert res.status_code == 201
    s = res.json()
    assert s["seed"] == 777 and s["generated"] == 5 and s["strategy"] == "balanced"
    assert all(len(c["numbers"]) == 6 for c in s["combinations"])

    again = client.post("/api/generate", json=GEN_BODY).json()
    assert [c["numbers"] for c in again["combinations"]] == [c["numbers"] for c in s["combinations"]]
    assert again["id"] != s["id"]

    assert [x["id"] for x in client.get("/api/sessions?game=mega645").json()] == [again["id"], s["id"]]
    assert client.get(f"/api/sessions/{s['id']}").json()["params"]["seed"] == 777

    csv_res = client.get(f"/api/sessions/{s['id']}/export.csv")
    assert csv_res.headers["content-type"].startswith("text/csv")
    assert "seed777" in csv_res.headers["content-disposition"]

    r = client.post(f"/api/sessions/{s['id']}/reproduce").json()
    assert r["matches"] and r["dataset_matches"]


def test_generate_random_seed_and_overrides(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    body = {**GEN_BODY, "seed": None, "weights": {"gap": 0}, "gap_mode": "recency",
            "rules": {"oversample": 2, "odd_penalty": 0}}
    s = client.post("/api/generate", json=body).json()
    assert 100_000 <= s["seed"] < 1_000_000
    assert s["params"]["scoring"]["weights"]["gap"] == 0
    assert s["params"]["rules"]["oversample"] == 2 and s["params"]["rules"]["odd_penalty"] == 0


def test_reproduce_detects_changed_data(client, fake_provider):
    client.post("/api/data/fetch", json=FETCH_BODY)
    s = client.post("/api/generate", json=GEN_BODY).json()
    extra = DrawResult.create(MEGA_645, "00004", date(2024, 1, 10), [2, 9, 17, 26, 35, 44])
    conn = connect(client.app.state.settings.db_path)
    SqliteDrawRepository(conn).save_draws(MEGA_645, [extra])
    conn.close()
    r = client.post(f"/api/sessions/{s['id']}/reproduce").json()
    assert r["dataset_matches"] is False and r["note"]


def test_generate_validation(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    assert client.post("/api/generate", json={**GEN_BODY, "count": 0}).status_code == 422
    assert client.post("/api/generate", json={**GEN_BODY, "strategy": "ml"}).status_code == 404
    assert client.post("/api/generate", json={**GEN_BODY, "weights": {"luck": 1}}).status_code == 422
    assert client.post("/api/generate", json={**GEN_BODY, "rules": {"sum_percentiles": [90, 10]}}).status_code == 422
    assert client.post("/api/generate", json={**GEN_BODY, "game": "power655"}).status_code == 422  # no data
    assert client.get("/api/sessions/12345").status_code == 404


def _wait_backtest(client, run_id, timeout=30):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/backtests/{run_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("backtest did not finish")


def test_backtest_endpoints(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    body = {"game": "mega645", "start": "2024-01-05", "end": "2024-01-31", "min_history": 10,
            "combinations_per_draw": 10, "strategies": ["frequency"], "custom": {"base": "recent", "gap_mode": "recency"}}
    # Only 1 prior draw before 2024-01-05 → every target is skipped, but the run completes.
    res = client.post("/api/backtests", json=body)
    assert res.status_code == 202
    run = _wait_backtest(client, res.json()["id"])
    assert run["status"] == "done", run["error"]
    assert run["result"]["n_targets"] == 0 and run["result"]["skipped"] == 2
    assert [s["label"] for s in run["params"]["strategies"]] == ["random", "frequency", "custom"]
    assert "targets" not in run["result"]
    assert client.get(f"/api/backtests/{run['id']}?targets=true").json()["result"]["targets"] == []
    assert client.get(f"/api/backtests/{run['id']}/export.csv").status_code == 200
    assert client.get("/api/backtests?game=mega645").json()[0]["id"] == run["id"]


def test_backtest_validation(client):
    client.post("/api/data/fetch", json=FETCH_BODY)
    base = {"game": "mega645", "start": "2024-01-01", "end": "2024-01-31"}
    assert client.post("/api/backtests", json={**base, "strategies": ["magic"]}).status_code == 422
    assert client.post("/api/backtests", json={**base, "start": "2025-01-01", "end": "2025-02-01"}).status_code == 422
    assert client.post("/api/backtests", json={**base, "end": "2023-01-01"}).status_code == 422
    assert client.get("/api/backtests/999").status_code == 404


def test_dashboard_includes_charts(client):
    html = client.get("/").text
    for element_id in ("number-chart", "sum-chart", "odd-chart", "low-chart", "score-chart", "bt-chart"):
        assert f'id="{element_id}"' in html
    assert client.get("/static/charts.js").status_code == 200
