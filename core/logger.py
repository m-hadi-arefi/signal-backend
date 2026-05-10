import json
import time


def log(service, level, trace_id, step, event=None, error=None):
    payload = {
        "service": service,
        "level": level,
        "trace_id": trace_id,
        "step": step,
        "event": event,
        "error": str(error) if error else None,
        "timestamp": time.time()
    }

    print(json.dumps(payload))