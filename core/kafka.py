from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import NoBrokersAvailable
import json
import time
from core.config import settings


# -------------------------
# Producer with retry
# -------------------------
def get_producer(max_retries: int = 10, delay: int = 5):
    """
    Try to create a KafkaProducer with retries if brokers are not ready.
    :param max_retries: maximum retry attempts
    :param delay: seconds to wait between retries
    """
    for attempt in range(1, max_retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BROKER,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=5
            )
            print(f"[KafkaProducer] Broker available after {attempt}/{max_retries} attempts")
            return producer
        except NoBrokersAvailable:
            print(f"[KafkaProducer] Broker not available, retry {attempt}/{max_retries}. Waiting {delay}s...")
            time.sleep(delay)
    raise Exception("KafkaProducer could not connect after multiple retries")


# -------------------------
# Consumer factory
# -------------------------
def get_consumer(topic: str, group_id: str):
    return KafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BROKER,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8"))
    )