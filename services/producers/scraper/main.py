import asyncio

from core.kafka_client import get_producer
from core.trace import ensure_trace
from services.producers.scraper.detector import extract_post_links
from services.producers.scraper.fetcher import fetch
from services.producers.scraper.parser import parse_content
from services.producers.scraper.rss_reader import fetch_rss_entries
from services.producers.scraper.tracker import SeenTracker
from core.source_loader import load_scraper_sources
from shared.enums.workflows import WORKFLOWS

SCRAPE_INTERVAL = 3600


async def process_source(source: dict, producer, tracker: SeenTracker):
    name = source["name"]

    try:
        if "rss" in source:
            entries = fetch_rss_entries(source)
            items = [
                {"url": e["url"], "title": e["title"], "text": e.get("text", "")}
                for e in entries if e.get("url")
            ]
        else:
            html  = fetch(source["listing_url"])
            items = [{"url": u, "title": "", "text": ""} for u in extract_post_links(html, source)]

        if not items:
            print(f"[SCRAPER] {name}: no URLs found")
            return

        # First-time seed — mark latest article, skip processing
        if not tracker.is_initialized(name):
            tracker.mark_seen(items[0]["url"])
            tracker.set_initialized(name)
            print(f"[SCRAPER] {name}: initialized → {items[0]['url']}")
            return

        new_count = 0

        for item in items:
            url = item["url"]
            if tracker.is_seen(url):
                continue

            try:
                if item.get("text"):
                    content = parse_content(item["text"])
                    if not content["title"]:
                        content["title"] = item["title"]
                else:
                    post_html = fetch(url)
                    content   = parse_content(post_html)

                event = ensure_trace({
                    "type":     "scraped.page",
                    "pipeline": WORKFLOWS["text_pipeline"],

                    # Source metadata — required by FinalEventSchema
                    "source": {
                        "type":     "scraper",
                        "provider": name,
                        "url":      url,
                    },

                    "payload": {
                        "url":     url,
                        "source":  name,
                        "title":   content["title"],
                        "payload": content["text"],
                    },
                })

                await producer.send_and_wait("engine-events", event)
                tracker.mark_seen(url)
                new_count += 1

            except Exception as e:
                print(f"[SCRAPER] {name}: error on {url}: {e}")

        if new_count:
            print(f"[SCRAPER] {name}: {new_count} new article(s) sent")
        else:
            print(f"[SCRAPER] {name}: nothing new")

    except Exception as e:
        print(f"[SCRAPER] {name}: source error: {e}")


async def scrape_once(producer, tracker: SeenTracker):
    sources = await load_scraper_sources()
    for source in sources:
        await process_source(source, producer, tracker)


async def run():
    print("[SCRAPER] started")
    producer = await get_producer()
    tracker  = SeenTracker()

    try:
        while True:
            await scrape_once(producer, tracker)
            await asyncio.sleep(SCRAPE_INTERVAL)
    except asyncio.CancelledError:
        print("[SCRAPER] shutting down")


if __name__ == "__main__":
    asyncio.run(run())
