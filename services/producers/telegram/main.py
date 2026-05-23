import asyncio

from telethon import TelegramClient, events

from core.kafka_client import get_producer
from core.trace import ensure_trace
from shared.enums.workflows import WORKFLOWS

from services.producers.telegram.client import client, PHONE


KAFKA_TOPIC = "engine-events"


# -------------------------
# telegram client
# -------------------------



# -------------------------
# handler
# -------------------------
async def handle_message(event, producer):

    try:
        message = event.message

        event_data = ensure_trace({
            "type": "telegram.message",

            "pipeline": WORKFLOWS["telegram_pipeline"],

            "payload": {
                "message_id": message.id,
                "text": message.message,
                "chat_id": event.chat_id,
                "sender_id": message.sender_id,
                "date": str(message.date)
            }
        })

        await producer.send_and_wait(
            KAFKA_TOPIC,
            event_data
        )

        print(f"[TELEGRAM] sent message {message.id}")

    except Exception as e:
        print(f"[TELEGRAM] error: {e}")


# -------------------------
# main
# -------------------------
async def run():

    print("[TELEGRAM] starting producer...")

    producer = await get_producer()

    await client.start()

    print("[TELEGRAM] connected")

    @client.on(events.NewMessage)
    async def handler(event):
        await handle_message(event, producer)

    await client.run_until_disconnected()


# -------------------------
# entrypoint
# -------------------------
if __name__ == "__main__":
    asyncio.run(run())
