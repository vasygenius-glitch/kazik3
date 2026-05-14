import time
from typing import Any, Dict, Optional, Tuple

class CacheManager:
    """A thread-safe-ish (for asyncio) generic cache manager with TTL."""
    def __init__(self, default_ttl: float = 60.0):
        self.default_ttl = default_ttl
        self._cache: Dict[Any, Tuple[Any, float]] = {}

    def get(self, key: Any) -> Optional[Any]:
        if key in self._cache:
            value, expiration = self._cache[key]
            if time.time() < expiration:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: Any, value: Any, ttl: Optional[float] = None):
        if ttl is None:
            ttl = self.default_ttl
        expiration = time.time() + ttl
        self._cache[key] = (value, expiration)

    def delete(self, key: Any):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()

global_cache = CacheManager(default_ttl=60.0)
