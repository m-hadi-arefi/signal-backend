import asyncio
from typing import Dict, Any, Optional

from core.worker import BaseWorker
from core.logger import log

# -------------------------
# next step resolver
# -------------------------
def next_step(pipeline: list, trace: list) -> Optional[str]:
    if not pipeline:
        return None
    trace = trace or []
    for step in pipeline:
        if step not in trace:
            return step
    return None

class Engine(BaseWorker):
    def __init__(self):
        super().__init__(
            service_name="engine",
            topic="engine-events",
            group_id="engine-group"
        )

    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        trace_id = event.get("trace_id", "unknown")
        pipeline = event.get("pipeline", [])
        trace = event.get("trace", [])

        step = next_step(pipeline, trace)

        if step:
            topic = f"{step}-events"
            log("engine", "info", trace_id, f"dispatching to {step}", event)
            # The engine routes to dynamic topics, so we send manually here
            await self.producer.send_and_wait(topic, event)
        else:
            log("engine", "info", trace_id, "workflow completed", event)
        
        # We return None because we've already handled the dispatching
        return None

async def main():
    engine = Engine()
    await engine.run()

if __name__ == "__main__":
    asyncio.run(main())