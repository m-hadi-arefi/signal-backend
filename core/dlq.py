import time

from core.kafka_client import get_producer


# -------------------------
# DLQ sender (async-safe)
# -------------------------
class DLQProducer:

    def __init__(self):
        self.producer = None

    async def init(self):
        self.producer = await get_producer()

    async def send_to_dlq(self, event, error, stage):

        dlq_event = {
            "event": event,
            "error": str(error),
            "stage": stage,
            "timestamp": time.time()
        }

        await self.producer.send_and_wait(
            "dlq-events",
            dlq_event
        )

    async def close(self):
        if self.producer:
            await self.producer.stop()