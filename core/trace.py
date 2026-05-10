import uuid
from core.redis import get_redis
import json

redis = get_redis()

def ensure_trace(event):
    if "trace_id" not in event:
        event["trace_id"] = str(uuid.uuid4())
    redis.set(f"trace:{event["trace_id"]}", json.dumps(event))
    return event


def add_step(event: dict, step: str) -> dict:
    if "trace" not in event or not isinstance(event["trace"], list):
        event["trace"] = []

    if step not in event["trace"]:
        event["trace"].append(step)

    return event