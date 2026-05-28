"""
Scenario schema — version 1.0

A single trading opportunity extracted from an AI analysis.
One Signal can have many Scenarios (e.g. breakout long, rejection short,
invalidation scenario).
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

SCHEMA_VERSION = "1.0"

Direction = Literal["long", "short", "neutral", "conditional"]
ScenarioStatus = Literal["running", "success", "failed", "expired"]


class TakeProfitLevel(BaseModel):
    price: float
    label: Optional[str] = None


class ScenarioInput(BaseModel):
    """
    Parsed scenario data from AI output before DB storage.
    All fields optional — the AI may not extract every field.
    """
    model_config = {"strict": False, "extra": "ignore"}

    direction: Optional[str] = None       # long / short / neutral / conditional
    entry_point: Optional[float] = None
    entry_type: Optional[str] = None      # limit / market / breakout
    take_profits: Optional[List[TakeProfitLevel]] = None
    stop_loss: Optional[float] = None
    invalidation: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    status: ScenarioStatus = "running"
    raw: dict = {}                         # full original AI signal dict

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
            return max(0.0, min(1.0, f))
        except (TypeError, ValueError):
            return None
