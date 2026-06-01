import asyncio

from core.kafka_client import get_producer
from core.trace import ensure_trace
from core.text import clean_text
from services.producers.http_api.fetcher import fetch
from services.producers.http_api.parser import build_text, get_item_id, get_items
from services.producers.http_api.tracker import ApiTracker
from core.source_loader import load_http_api_sources
from shared.enums.workflows import WORKFLOWS

API_INTERVAL = 3600


async def process_source(source: dict, producer, tracker: ApiTracker):
    name = source["name"]

    try:
        data  = fetch(source)
        items = get_items(data, source.get("data_path"))

        if not items:
            print(f"[HTTP_API] {name}: no items found")
            return

        # First-time seed — mark the first item, skip processing
        if not tracker.is_initialized(name):
            first_id = get_item_id(items[0], source.get("id_field"))
            tracker.mark_seen(name, first_id)
            tracker.set_initialized(name)
            print(f"[HTTP_API] {name}: initialized → {first_id}")
            return

        new_count = 0

        for item in items:
            item_id = get_item_id(item, source.get("id_field"))

            if tracker.is_seen(name, item_id):
                continue

            try:
                text = build_text(item, source)

                event = ensure_trace({
                    "type":     "http_api.response",
                    "pipeline": WORKFLOWS["telegram_pipeline"],

                    # Source metadata — required by FinalEventSchema
                    "source": {
                        "type":        "api",
                        "provider":    name,
                        "external_id": str(item_id),
                    },

                    "payload": {
                        "source":    name,
                        "url":       source["url"],
                        "real_text": text,
                        "text":      clean_text(text),
                    },
                })

                await producer.send_and_wait("engine-events", event)
                tracker.mark_seen(name, item_id)
                new_count += 1

            except Exception as e:
                print(f"[HTTP_API] {name}: error on item {item_id}: {e}")

        if new_count:
            print(f"[HTTP_API] {name}: {new_count} new item(s) sent")
        else:
            print(f"[HTTP_API] {name}: nothing new")

    except Exception as e:
        print(f"[HTTP_API] {name}: source error: {e}")


async def api_once(producer, tracker: ApiTracker):
    sources = await load_http_api_sources()
    for source in sources:
        await process_source(source, producer, tracker)


async def run():
    print("[HTTP_API] started")
    producer = await get_producer()
    tracker  = ApiTracker()

    try:
        while True:
            await api_once(producer, tracker)
            await asyncio.sleep(API_INTERVAL)
    except asyncio.CancelledError:
        print("[HTTP_API] shutting down")


if __name__ == "__main__":
    asyncio.run(run())
