import time
from collections import OrderedDict
from collections.abc import Callable


class MemoryCache:
    name = "memory"

    def __init__(self, *, maxsize: int = 1024, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._maxsize = maxsize
        self._clock = clock

    async def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    async def set(self, key: str, value: str, *, ttl: int) -> None:
        self._entries[key] = (value, self._clock() + ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    async def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    async def aclose(self) -> None:
        self._entries.clear()
