import asyncio
from bs4 import BeautifulSoup
from core.config import settings
from core.kafka_client import (
    get_consumer,
    get_producer,
    safe_commit
)

from core.logger import log
from core.kafka_client import start_consumer_with_stability


# -------------------------
# html cleaner
# -------------------------
def clean(html: str) -> str:

    return BeautifulSoup(
        html,
        "html.parser"
    ).get_text()


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

        raw_html = event["payload"]["payload"]

        # extract text
        text = clean(raw_html)

        event["text"] = text

        # ensure trace exists
        event.setdefault("trace", [])

        if "html" not in event["trace"]:
            event["trace"].append("html")

        log(
            "html",
            "info",
            event.get("trace_id"),
            "html",
            event
        )

        # return to engine
        await producer.send_and_wait(
            "engine-events",
            event
        )

        # commit ONLY after successful send
        await safe_commit(consumer)

    except Exception as e:

        log(
            "html",
            "error",
            event.get("trace_id"),
            "html",
            event,
            error=str(e)
        )


# -------------------------
# main loop
# -------------------------
async def run():
    print("[html-worker] started")

    consumer = get_consumer(
        "html-events",
        "html-group"
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