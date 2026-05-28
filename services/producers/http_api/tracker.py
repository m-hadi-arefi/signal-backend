import hashlib
from core.redis import get_redis


class ApiTracker:

    def __init__(self):
        self._r = get_redis()

    def _key(self, name: str, item_id: str) -> str:
        h = hashlib.sha256(f"{name}:{item_id}".encode()).hexdigest()[:16]
        return f"http_api:seen:{h}"

    def _init_key(self, name: str) -> str:
        return f"http_api:init:{name}"

    def is_seen(self, name: str, item_id: str) -> bool:
        return bool(self._r.exists(self._key(name, item_id)))

    def mark_seen(self, name: str, item_id: str, ttl_days: int = 30):
        self._r.set(self._key(name, item_id), 1, ex=ttl_days * 86400)

    def is_initialized(self, name: str) -> bool:
        return bool(self._r.exists(self._init_key(name)))

    def set_initialized(self, name: str):
        self._r.set(self._init_key(name), 1)
