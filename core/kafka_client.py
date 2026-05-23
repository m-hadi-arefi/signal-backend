import json
import asyncio
import time
import logging
from typing import Optional, List

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError, CommitFailedError, GroupCoordinatorNotAvailableError

from core.config import settings

# Structured logging for startup
logger = logging.getLogger("kafka-startup")

# -------------------------
# Singleton Producer
# -------------------------
class KafkaProducerSingleton:
    _instance: Optional[AIOKafkaProducer] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls) -> AIOKafkaProducer:
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = await cls._create_producer()
        return cls._instance

    @classmethod
    async def _create_producer(cls, max_retries: int = 15) -> AIOKafkaProducer:
        # Note: entrypoint.sh already waits for Kafka via bootstrap.py

        for attempt in range(1, max_retries + 1):
            try:
                producer = AIOKafkaProducer(
                    bootstrap_servers=settings.KAFKA_BROKER,
                    value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                    key_serializer=lambda k: str(k).encode("utf-8") if k else None,
                    acks="all",
                    enable_idempotence=True,
                    retry_backoff_ms=1000,
                    request_timeout_ms=30000
                )
                await producer.start()
                print(f"[KafkaProducer] Connected successfully (attempt {attempt})")
                return producer
            except Exception as e:
                delay = min(2 ** attempt, 30)
                print(f"[KafkaProducer] Connection failed (attempt {attempt}/{max_retries}): {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
        raise RuntimeError("Failed to start Kafka Producer after max retries")

    @classmethod
    async def close(cls):
        if cls._instance:
            await cls._instance.stop()
            cls._instance = None


# -------------------------
# Public Helpers
# -------------------------
async def get_producer() -> AIOKafkaProducer:
    """Returns the shared Kafka producer instance."""
    return await KafkaProducerSingleton.get_instance()


async def safe_commit(consumer: AIOKafkaConsumer, retries: int = 3) -> bool:
    """Safely commit offsets with retries."""
    for i in range(retries):
        try:
            await consumer.commit()
            return True
        except CommitFailedError:
            await asyncio.sleep(0.5 * (i + 1))
        except Exception as e:
            print(f"[Kafka] Commit error: {e}")
            break
    return False


def get_consumer(topic: str, group_id: str) -> AIOKafkaConsumer:
    """
    Creates a configured AIOKafkaConsumer.
    
    Using auto_offset_reset="earliest" to prevent message loss on startup.
    Tradeoff: If the consumer group is brand new, it will read all messages in the topic.
    Mitigation: Ensure topic retention is configured correctly in Kafka.
    """
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BROKER,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",  # Crucial for preventing loss
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        session_timeout_ms=45000,
        heartbeat_interval_ms=10000,
        max_poll_interval_ms=300000,
        retry_backoff_ms=1000
    )


async def start_consumer_with_stability(consumer: AIOKafkaConsumer, max_retries: int = 20):
    """
    Starts a consumer with exponential backoff and coordinator readiness check.
    Note: entrypoint.sh already handles broker/topic readiness.
    """
    # Start with exponential backoff to handle group coordinator election
    for attempt in range(1, max_retries + 1):
        try:
            await consumer.start()
            print(f"[KafkaConsumer] Started successfully and joined group '{consumer._group_id}'")
            return
        except GroupCoordinatorNotAvailableError:
            delay = min(2 ** attempt, 10)
            print(f"[KafkaConsumer] Coordinator not ready (attempt {attempt}). Retrying in {delay}s...")
            await asyncio.sleep(delay)
        except Exception as e:
            delay = min(2 ** attempt, 30)
            print(f"[KafkaConsumer] Start failed (attempt {attempt}/{max_retries}): {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)

    raise RuntimeError("Failed to start Kafka Consumer after multiple attempts")
