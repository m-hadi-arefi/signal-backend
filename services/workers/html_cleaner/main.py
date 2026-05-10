from core.retry import can_retry, increase_retry, retry_delay
from core.kafka import get_consumer, get_producer
from core.trace import ensure_trace, add_step
from core.dlq import send_to_dlq
from bs4 import BeautifulSoup
from core.logger import log
import time
from core.heartbeat import beat
from core.lag import get_lag
from shared.schema import Event

consumer = get_consumer("html-events", "html-group")
producer = get_producer()
SERVICE = "html_worker"

def clean_html(text):
    return BeautifulSoup(text, "html.parser").get_text()


for msg in consumer:
    print("lag:", get_lag(consumer))
    beat(SERVICE)
    event = Event(**msg.value).model_dump()
    event = ensure_trace(event)


    try:
        event["text"] = clean_html(event.get("text", ""))

        log(
            service=SERVICE,
            level="info",
            trace_id=event["trace_id"],
            step="html",
            event=event
        )

        event = add_step(event, "html")
        producer.send("engine-events", event)
        producer.flush()

        consumer.commit()

    except Exception as e:
        log(
            service=SERVICE,
            level="error",
            trace_id=event.get("trace_id"),
            step="html",
            event=event,
            error=e
        )
        if can_retry(event):
            event = increase_retry(event)
            retry_delay()

            producer.send("html-events", {
                **event,
                "retry_at": time.time() + 5
            })
            producer.flush()
        else:
            send_to_dlq(event, e, "html_cleaner")

        consumer.commit()