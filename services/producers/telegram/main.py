import asyncio

from telethon import TelegramClient, events

from core.kafka_client import get_producer
from core.trace import ensure_trace
from core.text import clean_text
from shared.enums.workflows import WORKFLOWS

from services.producers.telegram.client import client, PHONE

KAFKA_TOPIC      = "engine-signals"
_RECONNECT_DELAY = 10   # seconds to wait before reconnecting after a disconnect


async def handle_message(event, producer):
    try:
        message = event.message

        # Resolve channel username if available, fall back to numeric chat_id
        chat = await event.get_chat()
        channel_id = str(event.chat_id)
        channel_handle = (
            f"@{chat.username}" if getattr(chat, "username", None) else channel_id
        )

        raw_text = message.message or ""
        event_data = ensure_trace({
            "type": "telegram.message",
            "pipeline": WORKFLOWS["telegram_pipeline"],

            # Source metadata — required by FinalEventSchema
            "source": {
                "type":       "telegram",
                "provider":   "telegram",
                "channel":    channel_handle,
                "message_id": message.id,
            },

            "payload": {
                "message_id": message.id,
                "real_text":  raw_text,
                "text":       clean_text(raw_text),
                "chat_id":    event.chat_id,
                "sender_id":  message.sender_id,
                "date":       str(message.date),
            },
        })

        await producer.send_and_wait(KAFKA_TOPIC, event_data)
        print(f"[TELEGRAM] sent message {message.id} from {channel_handle}")

    except Exception as e:
        print(f"[TELEGRAM] error: {e}")


async def run():
    print("[TELEGRAM] starting producer...")

    producer = await get_producer()

    @client.on(events.NewMessage)
    async def handler(event):
        await handle_message(event, producer)

    while True:
        try:
            await client.start()
            print("[TELEGRAM] connected")
            await client.run_until_disconnected()
            print("[TELEGRAM] disconnected — reconnecting in %ds", _RECONNECT_DELAY)
        except Exception as e:
            print(f"[TELEGRAM] connection error: {e} — reconnecting in {_RECONNECT_DELAY}s")
        await asyncio.sleep(_RECONNECT_DELAY)


if __name__ == "__main__":
    asyncio.run(run())
