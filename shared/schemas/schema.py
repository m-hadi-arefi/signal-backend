from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class Event(BaseModel):
    trace_id: str
    type: str
    pipeline: List[str]
    payload: Dict[str, Any]

    trace: List[str] = []
    retry_count: int = 0

    text: Optional[str] = None
    ai: Optional[dict] = None

    class Config:
        extra = "allow"
    

class SignalEvent:
    symbol: str
    type: str
    price: float
    source: str
    timestamp: str