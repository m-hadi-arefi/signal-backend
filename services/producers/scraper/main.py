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

            event = ensure_trace({
                "type": "scraped.page",

                "pipeline":
                    WORKFLOWS["text_pipeline"],

                "payload": {
                    "url": url,
                    "payload": html
                }
            })

            await producer.send_and_wait(
                "engine-events",
                event
            )

            print(f"[SCRAPER] Scraped: {url}")

        except Exception as e:

            print(f"[SCRAPER] Error scraping {url}: {e}")


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

    except asyncio.CancelledError:

        print("[SCRAPER] shutting down")


# -------------------------
# entrypoint
# -------------------------
if __name__ == "__main__":
    asyncio.run(run())