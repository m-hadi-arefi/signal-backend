import asyncio
import json
from typing import Dict, Any, Optional
from services.workers.serializer.helper import clean_text
from core.worker import BaseWorker

class SerializerWorker(BaseWorker):
    def __init__(self):
        super().__init__(
            service_name="serializer",
            topic="serialize-events",
            group_id="serialize-group"
        )

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event.setdefault("trace", [])
        if "serialize" not in event["trace"]:
            event["trace"].append("serialize")
        
        payload = event.get("payload", {})
        text = payload.get("text")

        if not payload or not text:
            return None

        event["json"] = json.dumps(event["payload"], default=str)

        event["payload"]["real_text"] = text
        text = clean_text(text)
        event["payload"]["text"] = text

        print(f"[SERIALIZER] serialized: {text}")
        return event

async def run():
    worker = SerializerWorker()
    await worker.run()

if __name__ == "__main__":
    asyncio.run(run())
