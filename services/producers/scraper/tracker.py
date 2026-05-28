import hashlib
from core.redis import get_redis


class SeenTracker:

    def __init__(self):
        self._r = get_redis()

    def _key(self, url: str) -> str:
        return f"scraper:seen:{hashlib.sha256(url.encode()).hexdigest()[:16]}"

    def _init_key(self, name: str) -> str:
        return f"scraper:init:{name}"

    def is_seen(self, url: str) -> bool:
        return bool(self._r.exists(self._key(url)))

    def mark_seen(self, url: str, ttl_days: int = 30):
        self._r.set(self._key(url), 1, ex=ttl_days * 86400)

    def is_initialized(self, name: str) -> bool:
        return bool(self._r.exists(self._init_key(name)))

    def set_initialized(self, name: str):
        self._r.set(self._init_key(name), 1)
