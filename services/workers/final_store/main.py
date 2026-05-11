import asyncio

from services.workers.final_store.consumer import create_consumer
from services.workers.final_store.repository import EventRepository
from services.workers.final_store.processor import EventProcessor
from core.config import settings
from core.logger import log
from core.kafka_client import safe_commit
from core.kafka_client import start_consumer_with_stability


processor = EventProcessor()
repo = EventRepository()


# -------------------------
# handle event
# -------------------------
async def handle_event(msg, consumer):

    event = msg.value

    try:
        clean_event = processor.process(event)
        repo.upsert_event(clean_event)
        repo.db.commit()
        log(
            "final_store",
            "info",
            clean_event.get("trace_id"),
            "saved successfully",
            clean_event
        )
        await safe_commit(consumer)

    except Exception as e:

        try:
            repo.db.rollback()
        except:
            pass

        log(
            "final_store",
            "error",
            event.get("trace_id"),
            "failed to store event",
            event,
            error=str(e)
        )


# -------------------------
# main loop
# -------------------------
async def run():
    print("[final-store] started")

    consumer = create_consumer()

    await start_consumer_with_stability(consumer)

    try:

        async for msg in consumer:
            await handle_event(msg, consumer)
            
    except asyncio.CancelledError:
        print("[SHUTDOWN] cancelled")

    finally:

        await consumer.stop()
        repo.close()


# -------------------------
# entrypoint
# -------------------------
if __name__ == "__main__":
    asyncio.run(run())