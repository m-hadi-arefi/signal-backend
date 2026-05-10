from core.kafka import get_consumer, get_producer
from core.retry import can_retry, increase_retry
from core.db import get_connection
from core.trace import ensure_trace
from core.dlq import send_to_dlq
from core.logger import log
import json
from core.heartbeat import beat
from core.lag import get_lag
from shared.schema import Event
import time

consumer = get_consumer("final-events", "final-group")
producer = get_producer()
SERVICE = "final_worker"

conn = get_connection()
cur = conn.cursor()

for msg in consumer:
    print("lag:", get_lag(consumer))
    beat(SERVICE)
    event = Event(**msg.value).model_dump()
    event = ensure_trace(event)

    try:
        cur.execute(
            "INSERT INTO events (data) VALUES (%s)",
            (json.dumps(event),)
        )
        log(
            service=SERVICE,
            level="info",
            trace_id=event["trace_id"],
            step="final",
            event=event
        )

        conn.commit()
        consumer.commit()

    except Exception as e:
        log(
            service=SERVICE,
            level="error",
            trace_id=event.get("trace_id"),
            step="final",
            event=event,
            error=e
        )
        if can_retry(event):
            event = increase_retry(event)
            producer.send("final-events", {
                **event,
                "retry_at": time.time() + 5
            })
        else:
            send_to_dlq(event, e, "final_store")

        consumer.commit()