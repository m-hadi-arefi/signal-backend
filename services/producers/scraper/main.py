import time

from core.kafka import get_producer
from core.trace import ensure_trace

from shared.workflows import WORKFLOWS

from services.producers.scraper.fetcher import fetch
from services.producers.scraper.parser import parse
from services.producers.scraper.sources import SOURCES

producer = get_producer()
SCRAPE_INTERVAL = 3600  # 1 hour

def scrape_once():
    for url in SOURCES:
        try:
            html = fetch(url)
            #payload = parse(html)
            event = ensure_trace({
                "type": "scraped.page",
                "pipeline": WORKFLOWS["text_pipeline"],
                "payload": {
                    "url": url,
                    "payload": html
                }
            })
            producer.send("engine-events", event)
            print(f"[SCRAPED] {url}")
        except Exception as e:
            print(f"[ERROR] {url} -> {e}")


while True:
    scrape_once()
    time.sleep(SCRAPE_INTERVAL)
