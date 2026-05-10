from core.kafka import get_consumer, get_producer
from core.logger import log
from core.dlq import send_to_dlq
from core.retry import can_retry, increase_retry, retry_delay

consumer = get_consumer("engine-events", "engine-group")
producer = get_producer()


def get_next_topic(step: str) -> str:
    return f"{step}-events"


for msg in consumer:
    event = msg.value
    trace_id = event.get("trace_id", "no-trace-id")

    log(
        service="engine_worker",
        level="info",
        trace_id=trace_id,
        step="engine",
        event=event
    )

    pipeline = event.get("pipeline", [])
    if not pipeline:
        log(
            service="engine_worker",
            level="warning",
            trace_id=trace_id,
            step="engine",
            event="Pipeline empty"
        )
        consumer.commit()
        continue

    trace = event.get("trace", [])
    last_done = trace[-1] if trace else None

    next_step = None
    if last_done is None:
        next_step = pipeline[0]
    else:
        try:
            idx = pipeline.index(last_done)
            if idx + 1 < len(pipeline):
                next_step = pipeline[idx + 1]
        except ValueError:
            next_step = pipeline[0]

    if next_step:
        try:
            if next_step not in trace:
                event["trace"] = trace + [next_step]

            producer.send(get_next_topic(next_step), event)
            producer.flush()
            consumer.commit()

        except Exception as e:
            log(
                service="engine_worker",
                level="error",
                trace_id=trace_id,
                step="engine",
                event=event,
                error=e
            )
            if can_retry(event):
                event = increase_retry(event)
                retry_delay()
                producer.send(get_next_topic(next_step), event)
                producer.flush()
            else:
                send_to_dlq(event, e, "engine_worker")
            consumer.commit()
    else:
        log(
            service="engine_worker",
            level="info",
            trace_id=trace_id,
            step="engine",
            event="Pipeline completed"
        )
        consumer.commit()