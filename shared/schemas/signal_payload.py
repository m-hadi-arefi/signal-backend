"""
Final event payload schema — version 1.0

Validates the Kafka event that arrives at the final_store worker.
Signals that fail validation are dead-lettered to dlq-signals.
"""
from typing import List, Optional

from pydantic import BaseModel, field_validator

from shared.schemas.source import SourceMetadata

SCHEMA_VERSION = "1.0"


class MarketPriceSnapshot(BaseModel):
    """Redis price snapshot captured at analysis time."""
    price: float
    source: str       # e.g. "redis:btcusdt"
    timestamp: str    # ISO-8601


class FinalEventSchema(BaseModel):
    """
    Strict validation gate for events entering final_store.

    Required fields:
      - trace_id: non-empty UUID
      - type: event origin type
      - source: full SourceMetadata (producer must attach this)

    Optional:
      - signals: list of raw AI signal dicts (empty list is valid — nothing stored)
    """
    model_config = {"strict": False, "extra": "allow"}

    trace_id: str
    type: str
    source: SourceMetadata
    signals: List[dict] = []

    @field_validator("trace_id")
    @classmethod
    def _trace_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("trace_id must not be empty")
        return v.strip()

    @field_validator("type")
    @classmethod
    def _type_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("event type must not be empty")
        return v.strip()

    @field_validator("signals", mode="before")
    @classmethod
    def _signals_as_list(cls, v) -> list:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("signals must be a list")
        return [s for s in v if isinstance(s, dict)]
