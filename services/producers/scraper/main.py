import asyncio

from core.kafka_client import get_producer

from core.trace import ensure_trace
from services.producers.scraper.fetcher import fetch
from services.producers.scraper.sources import SOURCES

from shared.enums.workflows import WORKFLOWS


SCRAPE_INTERVAL = 3600


# -------------------------
# scrape once
# -------------------------
async def scrape_once(producer):

    for url in SOURCES:

        try:

            html = fetch(url)

            tasks = []

            event = ensure_trace({
                "type": "scraped.page",

                "pipeline":
                    WORKFLOWS["text_pipeline"],

                "payload": {
                    "url": url,
                    "payload": html
                }
            })

            # async kafka send
            tasks.append(
                producer.send_and_wait(
                    "engine-events",
                    event
                )
            )

            # wait all sends
            await asyncio.gather(*tasks)

            print(f"[SCRAPED] {url}")

        except Exception as e:

            print(f"[ERROR] {url} -> {e}")


# -------------------------
# main loop
# -------------------------
async def run():
    print("[SCRAPER] started")
    producer = await get_producer()

    try:

        while True:

            await scrape_once(producer)

            await asyncio.sleep(
                SCRAPE_INTERVAL
            )

    finally:

        await producer.stop()


# -------------------------
# entrypoint
# -------------------------
if __name__ == "__main__":
    asyncio.run(run())