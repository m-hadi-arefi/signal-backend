"""
Source metadata schema — version 1.0

Identifies where a signal originated. Attached to every Kafka event at the
producer layer and preserved through all pipeline stages to the Signal record.
"""
from typing import Literal, Optional

from pydantic import BaseModel, model_validator

SCHEMA_VERSION = "1.0"

SourceType = Literal["telegram", "scraper", "api"]


class SourceMetadata(BaseModel):
    model_config = {"strict": False, "extra": "ignore"}

    type: SourceType
    provider: str
    channel: Optional[str] = None    # telegram: @cointelegraph
    url: Optional[str] = None        # scraper: article URL
    external_id: Optional[str] = None  # api: provider's item ID

    @model_validator(mode="after")
    def _check_type_fields(self) -> "SourceMetadata":
        if self.type == "telegram" and not self.channel:
            raise ValueError("telegram source requires 'channel'")
        if self.type == "scraper" and not self.url:
            raise ValueError("scraper source requires 'url'")
        return self
