import asyncio
from aiokafka.admin import AIOKafkaAdminClient
from core.config import settings

TOPICS = [
    "engine-events",
    "ai-events",
    "final-events",
    "dlq-events"
]


async def sleep_backoff(i: int):
    await asyncio.sleep(min(2 ** i, 10))


async def wait_for_kafka_cluster(timeout=120):
    print("[Kafka] Waiting for broker...")

    start = asyncio.get_event_loop().time()
    i = 0

    while True:
        if asyncio.get_event_loop().time() - start > timeout:
            raise TimeoutError("Kafka not ready")

        try:
            admin = AIOKafkaAdminClient(
                bootstrap_servers=settings.KAFKA_BROKER
            )
            await admin.start()

            await admin.list_topics()

            await admin.close()

            print("[Kafka] Broker ready")
            return

        except Exception:
            i += 1
            await sleep_backoff(i)


async def ensure_topics():
    admin = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_BROKER
    )

    await admin.start()

    try:
        for _ in range(10):

            existing = set(await admin.list_topics())

            missing = [t for t in TOPICS if t not in existing]

            if not missing:
                print("[Kafka] All topics already exist")
                return

            from aiokafka.admin import NewTopic

            try:
                await admin.create_topics([
                    NewTopic(name=t, num_partitions=3, replication_factor=1)
                    for t in missing
                ])

                print(f"[Kafka] Created topics: {missing}")

            except Exception as e:
                print(f"[Kafka] create retry needed: {e}")

            await asyncio.sleep(2)

        raise Exception("Topics creation failed")

    finally:
        await admin.close()


async def bootstrap_kafka():
    await wait_for_kafka_cluster()
    await ensure_topics()

    print("[Kafka] READY 🚀")


if __name__ == "__main__":
    asyncio.run(bootstrap_kafka())