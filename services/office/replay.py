from core.kafka_client import get_producer


# -------------------------
# replay event
# -------------------------
async def replay_event(event):

    producer = await get_producer()

    try:

        event["pipeline"] = ["html"]

        await producer.send_and_wait(
            "html-events",
            event
        )

    finally:

        await producer.stop()