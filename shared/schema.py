from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class Event(BaseModel):
    trace_id: str
    version: int = 1
    type: str
    pipeline: Optional[List[str]] = []
    payload: Dict[str, Any]
    retry_count: Optional[int] = 0



