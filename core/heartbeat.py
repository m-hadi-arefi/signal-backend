import time
from core.redis import get_redis

redis = get_redis()


def beat(service_name):
    redis.set(
        f"heartbeat:{service_name}",
        int(time.time()),
        ex=10
    )


def is_alive(service_name):
    last = redis.get(f"heartbeat:{service_name}")
    if not last:
        return False

    return (int(time.time()) - int(last)) < 10