import json
import asyncio

from aiokafka import (
    AIOKafkaProducer,
    AIOKafkaConsumer
)

from aiokafka.errors import (
    KafkaConnectionError,
    CommitFailedError
)

from core.config import settings


# -------------------------
# safe commit helper
# -------------------------
async def safe_commit(
    consumer,
    retries: int = 3
):

    for i in range(retries):

        try:
            await consumer.commit()
            return True

        except CommitFailedError:

            await asyncio.sleep(
                0.5 * (i + 1)
            )

    return False


# -------------------------
# async producer factory
# -------------------------
async def get_producer(
    max_retries: int = 10,
    base_delay: float = 1.5,
    max_delay: float = 10
):

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

            print(
                f"[KafkaProducer] Connected successfully "
                f"({attempt}/{max_retries})"
            )

            return producer

        except KafkaConnectionError as e:

            delay = min(base_delay * attempt, max_delay)

            print(
                f"[KafkaProducer] Broker not ready "
                f"({attempt}/{max_retries}) -> retry in {delay}s | error: {e}"
            )

            await asyncio.sleep(delay)

        except Exception as e:

            # catch unexpected errors but still retry
            delay = min(base_delay * attempt, max_delay)

            print(
                f"[KafkaProducer] Unexpected error "
                f"({attempt}/{max_retries}) -> retry in {delay}s | error: {e}"
            )

            await asyncio.sleep(delay)

    raise RuntimeError(
        "KafkaProducer failed after max retries"
    )

# -------------------------
# async consumer factory
# -------------------------
def get_consumer(
    topic: str,
    group_id: str
):

    return AIOKafkaConsumer(
        topic,

        bootstrap_servers=settings.KAFKA_BROKER,

        group_id=group_id,

        enable_auto_commit=False,

        auto_offset_reset="latest",

        value_deserializer=lambda v:
            json.loads(
                v.decode("utf-8")
            ),

    session_timeout_ms=45000,
    heartbeat_interval_ms=10000,
    max_poll_interval_ms=300000
    )

async def start_consumer_with_stability(consumer):

    for i in range(10):
        try:
            await consumer.start()
            await asyncio.sleep(2) 

            print("Consumer stable")
            return

        except Exception as e:
            print(f"Consumer retry: {e}")
            await asyncio.sleep(2)