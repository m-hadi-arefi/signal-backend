import time
from core.kafka_client import get_producer

class DLQProducer:
    def __init__(self):
        self.producer = None

    async def _ensure_producer(self):
        if not self.producer:
            self.producer = await get_producer()

    async def send_to_dlq(self, event, error, stage):
        await self._ensure_producer()
        
        dlq_event = {
            "original_event": event,
            "error": str(error),
            "stage": stage,
            "timestamp": time.time()
        }

        await self.producer.send_and_wait(
            "dlq-events",
            dlq_event
        )

    async def close(self):
        # We don't stop the singleton producer here
        self.producer = None