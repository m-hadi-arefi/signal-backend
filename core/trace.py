import uuid

def ensure_trace(event):
    if not event.get("trace_id"):
        event["trace_id"] = str(uuid.uuid4())
    return event


def add_step(event, step):
    trace = event.get("trace", [])
    trace.append(step)
    event["trace"] = trace
    return event