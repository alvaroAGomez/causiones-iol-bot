import time
from config import Config


class CacheService:
    def __init__(self):
        self._cache = {"timestamp": 0, "data": []}

    def get(self):
        if time.time() - self._cache["timestamp"] < Config.CACHE_TTL_SECONDS:
            return self._cache["data"]
        return None

    def set(self, data):
        self._cache = {"timestamp": time.time(), "data": data}
