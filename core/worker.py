import asyncio
import abc
import os
from typing import Dict, Any, Optional
from core.kafka_client import (
    get_consumer,
    get_producer,
    safe_commit,
    start_consumer_with_stability
)
from core.logger import log
from core.dlq import DLQProducer
from core.pipeline_logger import log_pipeline

_HEARTBEAT_INTERVAL = 10   # seconds
_HEARTBEAT_TTL      = 30   # Redis key TTL (seconds)

# Services that return None from process_event as a normal "completed" signal
_NONE_MEANS_COMPLETED = {"engine", "final-store"}

# Sentinel file for Docker healthchecks
HEALTHCHECK_FILE = "/tmp/worker_ready"

class BaseWorker(abc.ABC):
    def __init__(self, service_name: str, topic: str, group_id: str):
        self.service_name = service_name
        self.topic = topic
        self.group_id = group_id
        self.consumer = None
        self.producer = None
        self.dlq = DLQProducer()
        self.running = False

    async def setup(self):
        self.consumer = get_consumer(self.topic, self.group_id)
        self.producer = await get_producer()
        await start_consumer_with_stability(self.consumer)
        self.signal_ready()

    def signal_ready(self):
        """Create a sentinel file to signal readiness to Docker."""
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                f.write("ready")
            print(f"[{self.service_name}] Ready signal created at {HEALTHCHECK_FILE}")
        except Exception as e:
            print(f"[{self.service_name}] Failed to create ready signal: {e}")

    def clear_ready(self):
        """Remove the sentinel file."""
        if os.path.exists(HEALTHCHECK_FILE):
            try:
                os.remove(HEALTHCHECK_FILE)
            except:
                pass

    @abc.abstractmethod
    async def process_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process the incoming event. 
        Return the modified event to be sent back to the engine, 
        or None if no further processing is needed (e.g. final store).
        """
        pass

    def _current_step_name(self) -> str:
        mapping = {
            "engine": "engine",
            "ai-worker": "ai",
            "final-store": "final",
        }
        return mapping.get(self.service_name, self.service_name)

    async def handle_message(self, msg):
        event = msg.value
        trace_id = event.get("trace_id") if isinstance(event, dict) else "unknown"

        await log_pipeline(trace_id, self.service_name, self._current_step_name(), "started", event)

        try:
            if not isinstance(event, dict):
                log(self.service_name, "error", trace_id, "invalid event type", event)
                await log_pipeline(trace_id, self.service_name, self._current_step_name(),
                                   "error", event, "invalid event type (not a dict)")
                await safe_commit(self.consumer)
                return

            # Process the event
            result_event = await self.process_event(event)

            if result_event is None:
                if self.service_name in _NONE_MEANS_COMPLETED:
                    await log_pipeline(trace_id, self.service_name, self._current_step_name(), "completed", event)
                else:
                    await log_pipeline(trace_id, self.service_name, self._current_step_name(), "dropped", event)
            else:
                await log_pipeline(trace_id, self.service_name, self._current_step_name(), "completed", result_event)
                await self.producer.send_and_wait("engine-signals", result_event)

            # Commit after success
            await safe_commit(self.consumer)

        except Exception as e:
            log(self.service_name, "error", trace_id, f"Processing failed: {str(e)}", event)
            await log_pipeline(trace_id, self.service_name, self._current_step_name(),
                               "error", event, str(e))

            # Send to DLQ
            try:
                await self.dlq.send_to_dlq(event, e, self.service_name)
                # Commit the original message so we don't get stuck in a loop
                await safe_commit(self.consumer)
                log(self.service_name, "info", trace_id, "Sent to DLQ and committed", event)
            except Exception as dlq_err:
                log(self.service_name, "critical", trace_id, f"Failed to send to DLQ: {str(dlq_err)}", event)
                # In case of DLQ failure, we might want to pause or retry differently
                # For now, we don't commit to avoid losing the message if DLQ is down
                await asyncio.sleep(5)

    async def _heartbeat_loop(self):
        """Write a Redis heartbeat key every _HEARTBEAT_INTERVAL seconds."""
        try:
            import redis.asyncio as aioredis
            r = aioredis.Redis(
                host=os.getenv("REDIS_HOST", "redis"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                decode_responses=True,
            )
            key = f"heartbeat:{self.service_name}"
            while self.running:
                try:
                    await r.setex(key, _HEARTBEAT_TTL, "1")
                except Exception:
                    pass
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
            await r.aclose()
        except Exception as e:
            print(f"[{self.service_name}] heartbeat init error: {e}")

    async def run(self):
        print(f"[{self.service_name}] starting on topic {self.topic}")
        self.clear_ready()
        await self.setup()
        self.running = True

        asyncio.create_task(self._heartbeat_loop())

        try:
            async for msg in self.consumer:
                if not self.running:
                    break
                await self.handle_message(msg)
        finally:
            await self.stop()

    async def stop(self):
        self.running = False
        self.clear_ready()
        if self.consumer:
            await self.consumer.stop()
        # Note: producer is a singleton, we don't stop it here unless the whole app stops
        await self.dlq.close()
        print(f"[{self.service_name}] stopped")
