import time
from collections import OrderedDict
from typing import Any, Optional


class CacheManager:
    """Bounded TTL/LRU cache for one asyncio thread; None denotes a miss."""
    def __init__(self, default_ttl: float = 60.0, max_size: int = 4096):
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache = OrderedDict()

    def get(self, key: Any) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, expiration = entry
        if time.monotonic() >= expiration:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def set(self, key: Any, value: Any, ttl: Optional[float] = None):
        ttl = self.default_ttl if ttl is None else ttl
        if ttl <= 0:
            self.delete(key)
            return
        if key not in self._cache and len(self._cache) >= self.max_size:
            self.prune()
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
        self._cache[key] = (value, time.monotonic() + ttl)
        self._cache.move_to_end(key)

    def prune(self):
        now = time.monotonic()
        for key, (_, expiry) in list(self._cache.items()):
            if expiry <= now:
                del self._cache[key]

    def delete(self, key: Any):
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()


global_cache = CacheManager(default_ttl=60.0)
