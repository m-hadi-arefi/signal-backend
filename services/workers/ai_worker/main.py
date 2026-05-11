import asyncio

from core.kafka_client import (
    get_consumer,
    get_producer,
    safe_commit
)
from core.config import settings
from core.logger import log
from core.kafka_client import start_consumer_with_stability


def fake_ai(text):
    return {
        "summary": text[:20] if text else ""
    }


# -------------------------
# process message
# -------------------------
async def handle_message(msg, consumer, producer):

    event = msg.value

    try:

        if not isinstance(event, dict):
            return

        event.setdefault("trace", [])

        text = event.get("text", "")

        # fake ai
        event["ai"] = fake_ai(text)

        if "ai" not in event["trace"]:
            event["trace"].append("ai")

        log(
            service="ai_worker",
            level="info",
            trace_id=event.get("trace_id"),
            step="ai",
            event=event
        )

        # return to engine
        await producer.send_and_wait(
            "engine-events",
            event
        )

        # commit after success
        await safe_commit(consumer)

    except Exception as e:

        log(
            service="ai_worker",
            level="error",
            trace_id=event.get("trace_id"),
            step="ai",
            event=event,
            error=str(e)
        )


# -------------------------
# main loop
# -------------------------
async def run():
    print("[ai-worker] started")
    consumer = get_consumer(
        "ai-events",
        "ai-group"
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

    finally:
        await consumer.stop()
        await producer.stop()

# -------------------------
# entrypoint
# -------------------------
if __name__ == "__main__":
    asyncio.run(run())