import asyncio
import os

_INTERVAL = 10  # seconds between writes
_TTL      = 30  # Redis key TTL


async def heartbeat_loop(service_name: str):
    """Write a Redis heartbeat key every _INTERVAL seconds. Run as a background task."""
    import redis.asyncio as aioredis
    r = aioredis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True,
    )
    key = f"heartbeat:{service_name}"
    try:
        while True:
            try:
                await r.setex(key, _TTL, "1")
            except Exception:
                pass
            await asyncio.sleep(_INTERVAL)
    except asyncio.CancelledError:
        pass
    finally:
        await r.aclose()
