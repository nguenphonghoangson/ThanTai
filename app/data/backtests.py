from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


class Status:
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class BacktestRun:
    id: int
    created_at: str
    updated_at: str
    status: str
    game: str
    params: dict
    progress: int
    total: int
    result: Optional[dict]
    error: Optional[str]

    def to_dict(self, include_targets: bool = False) -> dict:
        result = self.result
        if result is not None and not include_targets:
            result = {k: v for k, v in result.items() if k != "targets"}
        return {
            "id": self.id, "created_at": self.created_at, "updated_at": self.updated_at, "status": self.status,
            "game": self.game, "params": self.params, "progress": self.progress, "total": self.total,
            "result": result, "error": self.error,
        }

    def summary(self) -> dict:
        r = self.result or {}
        return {
            "id": self.id, "created_at": self.created_at, "status": self.status, "game": self.game,
            "start": self.params.get("start"), "end": self.params.get("end"),
            "strategies": [s["label"] for s in self.params.get("strategies", [])],
            "combinations_per_draw": self.params.get("combinations_per_draw"),
            "base_seed": self.params.get("base_seed"),
            "n_targets": r.get("n_targets"), "progress": self.progress, "total": self.total,
        }


class SqliteBacktestRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, game: str, params: dict) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO backtest_runs (status, game, params_json) VALUES (?, ?, ?)",
                (Status.RUNNING, game, json.dumps(params)),
            )
        return int(cur.lastrowid)

    def progress(self, run_id: int, done: int, total: int) -> None:
        with self._conn:
            self._conn.execute(
                f"UPDATE backtest_runs SET progress = ?, total = ?, updated_at = {NOW} WHERE id = ?",
                (done, total, run_id),
            )

    def finish(self, run_id: int, result: dict) -> None:
        with self._conn:
            self._conn.execute(
                f"UPDATE backtest_runs SET status = ?, result_json = ?, progress = total, updated_at = {NOW}"
                " WHERE id = ?",
                (Status.DONE, json.dumps(result), run_id),
            )

    def fail(self, run_id: int, error: str) -> None:
        with self._conn:
            self._conn.execute(
                f"UPDATE backtest_runs SET status = ?, error = ?, updated_at = {NOW} WHERE id = ?",
                (Status.FAILED, error, run_id),
            )

    def fail_interrupted(self) -> int:
        """Mark runs left 'running' by a previous process as failed."""
        with self._conn:
            cur = self._conn.execute(
                f"UPDATE backtest_runs SET status = ?, error = ?, updated_at = {NOW} WHERE status = ?",
                (Status.FAILED, "Interrupted: the server stopped before the run finished.", Status.RUNNING),
            )
        return cur.rowcount

    def get(self, run_id: int) -> Optional[BacktestRun]:
        row = self._conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        return _row(row) if row else None

    def list(self, game: Optional[str] = None, limit: int = 20) -> List[BacktestRun]:
        sql, args = "SELECT * FROM backtest_runs", []
        if game:
            sql += " WHERE game = ?"
            args.append(game)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [_row(r) for r in self._conn.execute(sql, args)]


def _row(row: sqlite3.Row) -> BacktestRun:
    return BacktestRun(
        id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"], status=row["status"],
        game=row["game"], params=json.loads(row["params_json"]), progress=row["progress"], total=row["total"],
        result=json.loads(row["result_json"]) if row["result_json"] else None, error=row["error"],
    )


def backtest_csv(run: BacktestRun) -> str:
    """Per-target results: one row per evaluated draw, mean and best matches per strategy."""
    buf = io.StringIO()
    p = run.params
    buf.write(f"# backtest={run.id} game={run.game} period={p['start']}..{p['end']} "
              f"per_draw={p['combinations_per_draw']} base_seed={p['base_seed']} "
              f"dataset={(run.result or {}).get('dataset_fingerprint')}\n")
    labels = [s["label"] for s in p["strategies"]]
    writer = csv.writer(buf)
    writer.writerow(["draw_id", "draw_date", "actual", "history", "seed",
                     *[f"{label}_mean" for label in labels], *[f"{label}_best" for label in labels]])
    for t in (run.result or {}).get("targets", []):
        writer.writerow([t["draw_id"], t["draw_date"], " ".join(f"{n:02d}" for n in t["actual"]), t["history"],
                         t["seed"], *[f"{t['mean'][label]:.4f}" for label in labels],
                         *[t["best"][label] for label in labels]])
    return buf.getvalue()
