"""Seeded weighted sampling of unique combinations."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from app.domain.games import LotteryGameConfig
from app.logging_config import log_event

logger = logging.getLogger(__name__)

Combination = Tuple[int, ...]

SAMPLER = "gumbel-top-k/pcg64"  # recorded with sessions; changing the algorithm changes outputs
MAX_ROUNDS = 50


@dataclass
class SampleResult:
    combinations: List[Combination]
    requested: int
    rounds: int
    notes: List[str] = field(default_factory=list)


def sample_combinations(
    game: LotteryGameConfig, weights: np.ndarray, count: int, seed: int
) -> SampleResult:
    """Draw ``count`` unique sorted combinations; each number's chance follows ``weights``.

    Each combination is a weighted draw without replacement (successive sampling, as with
    physical balls of unequal weight). Implemented with the Gumbel-top-k trick: adding
    independent Gumbel noise to log-weights and taking the k largest is equivalent to that
    sequential draw, and it vectorizes over many combinations at once.
    """
    if weights.shape != (game.pool_size,) or np.any(weights <= 0):
        raise ValueError("weights must be positive, one per number in the pool")
    if count < 1:
        raise ValueError("count must be >= 1")

    k = game.numbers_per_draw
    rng = np.random.Generator(np.random.PCG64(seed))
    log_w = np.log(weights / weights.sum())
    seen = set()
    out: List[Combination] = []
    rounds = 0
    while len(out) < count and rounds < MAX_ROUNDS:
        rounds += 1
        batch = max(2 * (count - len(out)), 16)
        u = rng.random((batch, game.pool_size))
        keys = log_w - np.log(-np.log(np.clip(u, 1e-300, None)))
        top = np.argpartition(-keys, k - 1, axis=1)[:, :k]
        rows = (np.sort(top, axis=1) + game.min_number).tolist()
        for combo in map(tuple, rows):
            if combo not in seen:
                seen.add(combo)
                out.append(combo)
                if len(out) == count:
                    break

    notes = []
    if len(out) < count:
        notes.append(f"Only {len(out)} unique combinations found after {rounds} rounds (requested {count}).")
    log_event(logger, "combination.sampled", logging.DEBUG, game=game.key, requested=count, produced=len(out),
              rounds=rounds, seed=seed)
    return SampleResult(out, count, rounds, notes)
