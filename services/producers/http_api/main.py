# import time

# from core.kafka_client import get_producer
# from core.trace import ensure_trace

# from shared.workflows import WORKFLOWS

# from services.producers.http_api.fetcher import fetch
# from services.producers.http_api.parser import parse
# from services.producers.http_api.sources import SOURCES

# producer = await get_producer()
# HTTP_API_INTERVAL = 3600  # 1 hour

# def http_api_once():
#     for url in SOURCES:
#         try:
#             html = fetch(url)
#             payload = parse(html)
#             event = ensure_trace({
#                 "type": "http_api.page",
#                 "steps": WORKFLOWS["text_pipeline"],
#                 "payload": {
#                     "url": url,
#                     **payload
#                 }
#             })
#             producer.send("engine-events", event)
#             print(f"[HTTP_API] {url}")
#         except Exception as e:
#             print(f"[ERROR] {url} -> {e}")


# while True:
#     http_api_once()
#     time.sleep(HTTP_API_INTERVAL)
print("http_api producer is not implemented")