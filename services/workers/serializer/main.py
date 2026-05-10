from core.kafka import get_consumer, get_producer
from core.dlq import send_to_dlq
from core.retry import can_retry, increase_retry, retry_delay
from core.trace import ensure_trace, add_step
from core.logger import log
import json
from core.lag import get_lag
from shared.schema import Event
from core.heartbeat import beat
import time

consumer = get_consumer("serialize-events", "serializer-group")
producer = get_producer()


SERVICE = "serialize_worker"

for msg in consumer:
    print("lag:", get_lag(consumer))
    beat(SERVICE)
    event = Event(**msg.value).model_dump()
    event = ensure_trace(event)

    try:
        event["json"] = json.dumps(event)
        log(
            service=SERVICE,
            level="info",
            trace_id=event["trace_id"],
            step="serialize",
            event=event
        )
        event = add_step(event, "serialize")
        producer.send("engine-events", event)
        producer.flush()
        consumer.commit()

    except Exception as e:
        log(
            service=SERVICE,
            level="error",
            trace_id=event.get("trace_id"),
            step="serialize",
            event=event,
            error=e
        )

        if can_retry(event):
            event = increase_retry(event)
            retry_delay()
            producer.send("serialize-events", {
                **event,
                "retry_at": time.time() + 5
            })
            producer.flush()
        else:
            send_to_dlq(event, e, "serializer")
        consumer.commit()