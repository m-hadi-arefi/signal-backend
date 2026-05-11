import asyncio
import json

from core.kafka_client import (
    get_consumer,
    get_producer,
    safe_commit
)

from core.logger import log
from core.kafka_client import start_consumer_with_stability


# -------------------------
# process message
# -------------------------
async def handle_message(
    msg,
    consumer,
    producer
):

    event = msg.value

    try:

        if not isinstance(event, dict):
            return

        # ensure trace exists
        event.setdefault("trace", [])

        if "serialize" not in event["trace"]:
            event["trace"].append("serialize")

        # serialize full event
        event["json"] = json.dumps(
            event,
            default=str
        )

        log(
            service="serialize",
            level="info",
            trace_id=event.get("trace_id"),
            step="serialize",
            event=event
        )

        # return to engine
        await producer.send_and_wait(
            "engine-events",
            event
        )

        # commit ONLY after success
        await safe_commit(consumer)

    except Exception as e:

        log(
            service="serialize",
            level="error",
            trace_id=event.get("trace_id"),
            step="serialize",
            event=event,
            error=str(e)
        )


# -------------------------
# main loop
# -------------------------
async def run():
    print("[serialize-worker] started")


    consumer = get_consumer(
        "serialize-events",
        "serialize-group"
    )

    producer = await get_producer()

    await start_consumer_with_stability(consumer)

    try:

        async for msg in consumer:

            await handle_message(
                msg,
                consumer,
                producer
            )
    except asyncio.CancelledError:
        print("[SHUTDOWN] cancelled")
    finally:

        await consumer.stop()
        await producer.stop()


# -------------------------
# entrypoint
# -------------------------
if __name__ == "__main__":
    asyncio.run(run())