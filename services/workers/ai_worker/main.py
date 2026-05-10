from core.retry import can_retry, increase_retry, retry_delay
from core.kafka import get_consumer, get_producer
from core.trace import ensure_trace, add_step
from core.dlq import send_to_dlq
from core.logger import log
from core.heartbeat import beat
from core.lag import get_lag
from shared.schema import Event
import time 

SERVICE = "ai_worker"
consumer = get_consumer("ai-events", "ai-group")
producer = get_producer()


def fake_ai(text):
    return {"summary": text[:20]}

for msg in consumer:
    print("lag:", get_lag(consumer))
    beat(SERVICE)
    event = Event(**msg.value).model_dump()
    event = ensure_trace(event)

    try:
        event["ai"] = fake_ai(event["text"])
        log(
            service=SERVICE,
            level="info",
            trace_id=event["trace_id"],
            step="html",
            event=event
        )
        event = add_step(event, "ai")
        producer.send("engine-events", event)
        producer.flush()

        consumer.commit()

    except Exception as e:
        log(
            service=SERVICE,
            level="info",
            trace_id=event["trace_id"],
            step="ai",
            event=event
        )
        if can_retry(event):
            event = increase_retry(event)
            retry_delay()

            producer.send("ai-events", {
                **event,
                "retry_at": time.time() + 5
            })
            producer.flush()
        else:
            send_to_dlq(event, e, "ai_worker")

        consumer.commit()