# from core.kafka_client import get_producer
# from telethon import events
# from shared.workflows import WORKFLOWS
# from services.producers.telegram.client import client
# from services.producers.telegram.parser import parse_message
# producer = await get_producer()

# @client.on(events.NewMessage)
# async def handler(event):
#     payload = parse_message(event)
#     producer.send("engine-events", {
#         "type": "telegram.message",
#         "steps": WORKFLOWS["text_pipeline"],
#         "payload": payload
#     })

# client.start()
# client.run_until_disconnected()

print("telegram producer is not implemented")