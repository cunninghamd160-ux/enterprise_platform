import asyncio
import functools
import hashlib
import inspect
import json
import os
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

from opentelemetry.trace import Span, SpanKind

from insights_platform import audit, config
from insights_platform.cache._memory import MemoryCache
from insights_platform.cache._redis import RedisCache
from insights_platform.observability import get_meter, get_tracer

__all__ = [
    "CACHE_URL_ENV",
    "Backend",
    "Cache",
    "CacheValueError",
    "JsonValue",
    "MemoryCache",
    "RedisCache",
    "cached",
    "get_cache",
    "reset_cache",
]

CACHE_URL_ENV = "INSIGHTS_CACHE_URL"

type JsonValue = str | int | float | bool | Sequence[JsonValue] | Mapping[str, JsonValue] | None


class CacheValueError(TypeError):
    pass


class Cache(Protocol):
    async def get(self, key: str) -> JsonValue | None: ...

    async def set(self, key: str, value: JsonValue, *, ttl: int) -> None: ...

    async def delete(self, key: str) -> None: ...


class Backend(Protocol):
    name: str

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def aclose(self) -> None: ...


class _Instrumented:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self._tracer = get_tracer("insights.cache")
        self._hits = get_meter("insights.cache").create_counter(
            "insights.cache.hits", unit="1", description="Cache reads by result (hit or miss)"
        )

    async def get(self, key: str) -> JsonValue | None:
        qualified = _qualify(key)
        with self._span("cache.get") as span:
            text = await self.backend.get(qualified)
            result = "miss" if text is None else "hit"
            span.set_attribute("cache.result", result)
        self._hits.add(1, {"result": result})
        return None if text is None else _decode(text)

    async def set(self, key: str, value: JsonValue, *, ttl: int) -> None:
        _check_ttl(ttl)
        text = _encode(value)
        qualified = _qualify(key)
        audit.emit("cache.set", key_sha256=_sha256(qualified), ttl=ttl)
        with self._span("cache.set"):
            await self.backend.set(qualified, text, ttl=ttl)

    async def delete(self, key: str) -> None:
        qualified = _qualify(key)
        audit.emit("cache.delete", key_sha256=_sha256(qualified))
        with self._span("cache.delete"):
            await self.backend.delete(qualified)

    async def aclose(self) -> None:
        await self.backend.aclose()

    def _span(self, name: str) -> AbstractContextManager[Span]:
        return self._tracer.start_as_current_span(
            name, kind=SpanKind.CLIENT, attributes={"cache.backend": self.backend.name}
        )


_cache: _Instrumented | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = _Instrumented(_build_backend())
    return _cache


def reset_cache() -> None:
    global _cache
    cache, _cache = _cache, None
    if cache is not None:
        asyncio.run(cache.aclose())


def cached[F: Callable[..., Coroutine[Any, Any, Any]]](*, ttl: int) -> Callable[[F], F]:
    _check_ttl(ttl)

    def decorate(fn: F) -> F:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"@cached wraps async def functions only; {fn.__qualname__} is not one")
        signature = inspect.signature(fn)
        prefix = f"{fn.__module__}.{fn.__qualname__}:"

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = prefix + _sha256(_arguments_json(signature, args, kwargs))
            cache = get_cache()
            hit = await cache.get(key)
            if hit is not None:
                return hit
            result = await fn(*args, **kwargs)
            # None reads back as a miss, so storing it would only add a write per call.
            if result is not None:
                await cache.set(key, result, ttl=ttl)
            return result

        return cast(F, wrapper)

    return decorate


def _build_backend() -> Backend:
    url = os.environ.get(CACHE_URL_ENV)
    return RedisCache.from_url(url) if url else MemoryCache()


def _qualify(key: str) -> str:
    return f"{config.current().name}:{key}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _check_ttl(ttl: int) -> None:
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise TypeError(f"ttl must be an int number of seconds, got {type(ttl).__name__}")
    if ttl <= 0:
        raise ValueError(f"ttl must be a positive number of seconds, got {ttl}")


def _encode(value: JsonValue) -> str:
    # NaN and Infinity are not JSON; a reader in another language would reject the stored text.
    try:
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CacheValueError(
            f"cache values must be JSON (dict, list, str, int, float, bool, None): {exc}"
        ) from exc


def _decode(text: str) -> JsonValue:
    return cast(JsonValue, json.loads(text))


def _arguments_json(
    signature: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> str:
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    try:
        return json.dumps(bound.arguments, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CacheValueError(f"arguments to a @cached function must be JSON: {exc}") from exc
