"""Request bodies shared by several routers."""
from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.analysis.combination import CombinationRules


class RulesBody(BaseModel):
    odd_counts: Optional[List[int]] = None
    odd_penalty: Optional[float] = Field(None, ge=0)
    low_counts: Optional[List[int]] = None
    low_penalty: Optional[float] = Field(None, ge=0)
    min_spread_fraction: Optional[float] = Field(None, ge=0, le=1)
    spread_penalty: Optional[float] = Field(None, ge=0)
    sum_percentiles: Optional[List[int]] = Field(None, min_length=2, max_length=2)
    sum_penalty: Optional[float] = Field(None, ge=0)
    pair_weight: Optional[float] = Field(None, ge=0)
    oversample: Optional[int] = Field(None, ge=1, le=20)


def rules_from_body(body: RulesBody) -> CombinationRules:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return CombinationRules.from_dict(values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
