import asyncio

from core.kafka_client import (
    get_consumer,
    get_producer,
    safe_commit
)
from core.logger import log
from core.kafka_client import start_consumer_with_stability

# -------------------------
# next step resolver
# -------------------------
def next_step(pipeline, trace):

    if not pipeline:
        return None

    trace = trace or []

    for step in pipeline:
        if step not in trace:
            return step

    return None


# -------------------------
# dispatch
# -------------------------
async def dispatch(producer, event, step):

    topic = f"{step}-events"

    log(
        service="engine",
        level="info",
        trace_id=event.get("trace_id"),
        step=f"dispatch:{step}",
        event=event
    )

    await producer.send_and_wait(
        topic,
        event
    )


# -------------------------
# process
# -------------------------
async def process(producer, event):

    pipeline = event.get("pipeline", [])
    trace = event.get("trace", [])

    step = next_step(pipeline, trace)

    if step:
        await dispatch(producer, event, step)

    else:
        log(
            service="engine",
            level="info",
            trace_id=event.get("trace_id"),
            step="completed",
            event=event
        )


# -------------------------
# main loop
# -------------------------
async def main():

    consumer = get_consumer(
        "engine-events",
        "engine-group"
    )

    producer = await get_producer()

    await start_consumer_with_stability(consumer)

    try:
        async for msg in consumer:

            event = msg.value

            if not isinstance(event, dict):
                continue

            pipeline = event.get("pipeline", [])
            trace = event.get("trace", [])

            for step in pipeline:
                if step not in trace:
                    topic = f"{step}-events"

                    await producer.send_and_wait(topic, event)
                    break

    finally:
        await consumer.stop()
        await producer.stop()

if __name__ == "__main__":
    asyncio.run(main())