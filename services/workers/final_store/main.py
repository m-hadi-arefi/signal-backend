import asyncio
from typing import Dict, Any, Optional

from core.worker import BaseWorker
from services.workers.final_store.repository import EventRepository
from services.workers.final_store.processor import EventProcessor
from shared.database.session import SessionLocal

class FinalStoreWorker(BaseWorker):
    def __init__(self):
        super().__init__(
            service_name="final_store",
            topic="final-events",
            group_id="final-group"
        )
        self.processor = EventProcessor()

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        clean_event = self.processor.process(event)
        
        async with SessionLocal() as session:
            repo = EventRepository(session)
            try:
                await repo.upsert_event(clean_event)
            except Exception:
                await repo.rollback()
                raise
                
        # Return None as this is the final step
        return None

async def run():
    worker = FinalStoreWorker()
    await worker.run()

if __name__ == "__main__":
    asyncio.run(run())