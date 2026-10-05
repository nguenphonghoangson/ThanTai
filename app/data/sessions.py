from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from app.analysis.pipeline import GenerationResult
from app.logging_config import log_event

logger = logging.getLogger(__name__)


@dataclass
class StoredSession:
    id: int
    created_at: str
    game: str
    strategy: str
    seed: int
    count: int
    dataset_fingerprint: str
    params: dict
    combinations: List[dict]
    notes: List[str]

    def summary(self) -> dict:
        return {
            "id": self.id, "created_at": self.created_at, "game": self.game, "strategy": self.strategy,
            "seed": self.seed, "count": self.count, "generated": len(self.combinations),
            "start": self.params.get("start"), "end": self.params.get("end"),
            "dataset_fingerprint": self.dataset_fingerprint,
        }

    def to_dict(self) -> dict:
        return {**self.summary(), "params": self.params, "notes": self.notes, "combinations": self.combinations}


class SqliteSessionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, result: GenerationResult) -> int:
        p = result.params
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO generation_sessions (game, start_date, end_date, strategy, seed, count,"
                " dataset_fingerprint, params_json, combinations_json, notes_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["game"], p["start"], p["end"], p["strategy"], p["seed"], p["count"], p["dataset_fingerprint"],
                 json.dumps(p), json.dumps([c.to_dict() for c in result.combinations]), json.dumps(result.notes)),
            )
        session_id = int(cur.lastrowid)
        log_event(logger, "session.saved", id=session_id, game=p["game"], strategy=p["strategy"],
                  seed=p["seed"], generated=len(result.combinations))
        return session_id

    def get(self, session_id: int) -> Optional[StoredSession]:
        row = self._conn.execute("SELECT * FROM generation_sessions WHERE id = ?", (session_id,)).fetchone()
        return _row(row) if row else None

    def list(self, game: Optional[str] = None, limit: int = 20) -> List[StoredSession]:
        sql, args = "SELECT * FROM generation_sessions", []
        if game:
            sql += " WHERE game = ?"
            args.append(game)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [_row(r) for r in self._conn.execute(sql, args)]


def _row(row: sqlite3.Row) -> StoredSession:
    return StoredSession(
        id=row["id"], created_at=row["created_at"], game=row["game"], strategy=row["strategy"],
        seed=row["seed"], count=row["count"], dataset_fingerprint=row["dataset_fingerprint"],
        params=json.loads(row["params_json"]), combinations=json.loads(row["combinations_json"]),
        notes=json.loads(row["notes_json"]),
    )


def session_csv(session: StoredSession) -> str:
    """CSV with a commented header carrying the reproduction parameters."""
    buf = io.StringIO()
    p = session.params
    scoring = p["scoring"]
    buf.write(f"# session={session.id} game={session.game} strategy={session.strategy} seed={session.seed} "
              f"draws={p['n_draws']} range={p.get('start')}..{p.get('end')} dataset={session.dataset_fingerprint}\n")
    buf.write(f"# weights={json.dumps(scoring['effective_weights'])} intensity={scoring['intensity']} "
              f"gap_mode={scoring['gap_mode']} sampler={p['sampler']} numpy={p['numpy_version']}\n")
    buf.write("# Scores are relative weights from historical data, not probabilities of winning.\n")
    writer = csv.writer(buf)
    k = len(session.combinations[0]["numbers"]) if session.combinations else 0
    writer.writerow(["rank", *[f"n{i + 1}" for i in range(k)], "total_score", "number_score", "pair_score",
                     "distribution_score", "sum_score", "sum", "odd", "low", "flags"])
    for i, c in enumerate(session.combinations, start=1):
        writer.writerow([i, *c["numbers"], f"{c['total']:.4f}", f"{c['number_score']:.4f}", f"{c['pair_score']:.4f}",
                         f"{c['distribution_score']:.4f}", f"{c['sum_score']:.4f}", c["total_sum"], c["odd"], c["low"],
                         "; ".join(c["flags"])])
    return buf.getvalue()
