import asyncio
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest
from fakeredis.aioredis import FakeRedis
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from insights_platform import cache, config
from insights_platform.cache import (
    Backend,
    CacheValueError,
    JsonValue,
    MemoryCache,
    RedisCache,
    cached,
    get_cache,
    reset_cache,
)
from insights_platform.observability import Scalar, fields_of

type ManifestWriter = Callable[..., Path]

KEY = "employee:E001"
VALUE: dict[str, JsonValue] = {"id": "E001", "base_salary": "salary-secret", "tags": ["a", 1, None]}
KEY_SHA256 = hashlib.sha256(b"demo:employee:E001").hexdigest()

calls: list[tuple[object, ...]] = []


@cached(ttl=60)
async def lookup(employee_id: str, *, detail: bool = False) -> dict[str, JsonValue]:
    calls.append((employee_id, detail))
    return {"id": employee_id, "detail": detail}


@cached(ttl=60)
async def slow_square(x: int) -> int:
    calls.append((x,))
    await asyncio.sleep(0)
    return x * x


@cached(ttl=60)
async def nothing(x: int) -> None:
    calls.append((x,))


@cached(ttl=60)
async def stamp(x: int) -> datetime:
    return datetime(2026, 9, 9, x, tzinfo=UTC)


class ClosingFake(FakeRedis):
    closed = False

    async def aclose(self, close_connection_pool: bool | None = None) -> None:
        self.closed = True
        await super().aclose(close_connection_pool)


@pytest.fixture(autouse=True)
def _clear_calls() -> Iterator[None]:
    calls.clear()
    yield
    calls.clear()


@pytest.fixture(params=["memory", "redis"])
def backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Backend:
    store: Backend = (
        MemoryCache()
        if request.param == "memory"
        else RedisCache(ClosingFake(decode_responses=True))
    )
    monkeypatch.setattr(cache, "_build_backend", lambda: store)
    return store


@pytest.fixture
def demo(write_manifest: ManifestWriter) -> None:
    config.load(write_manifest(name="demo"))


@pytest.fixture
def hits(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    monkeypatch.setattr(cache, "get_meter", MeterProvider(metric_readers=[reader]).get_meter)
    return reader


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(cache, "get_tracer", provider.get_tracer)
    return exporter


def hit_counts(reader: InMemoryMetricReader) -> dict[str, int]:
    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    return {
        str(dict(point.attributes or {})["result"]): int(point.value)
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == "insights.cache.hits"
        for point in metric.data.data_points
    }


def audit_records(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, Scalar]]:
    return [fields_of(r) for r in caplog.records if r.getMessage() == event]


def stored_keys(backend: Backend) -> list[str]:
    if isinstance(backend, MemoryCache):
        return list(backend._entries)
    assert isinstance(backend, RedisCache)
    return sorted(asyncio.run(backend.client.keys("*")))


def test_round_trip_returns_an_equal_copy(backend: Backend, demo: None) -> None:
    async def scenario() -> None:
        store = get_cache()
        assert await store.get(KEY) is None
        await store.set(KEY, VALUE, ttl=60)
        first = await store.get(KEY)
        assert first == VALUE
        assert isinstance(first, dict)
        first["id"] = "mutated"
        assert await store.get(KEY) == VALUE
        await store.delete(KEY)
        assert await store.get(KEY) is None

    asyncio.run(scenario())


def test_json_semantics_are_identical_on_both_backends(backend: Backend, demo: None) -> None:
    async def scenario() -> None:
        store = get_cache()
        for value in (0, False, "", [], {}, 1.5, "text", None):
            await store.set("v", value, ttl=60)
            assert await store.get("v") == value
        await store.set("t", (1, 2), ttl=60)
        assert await store.get("t") == [1, 2]

    asyncio.run(scenario())


def test_keys_are_stored_under_the_app_prefix(backend: Backend, demo: None) -> None:
    asyncio.run(get_cache().set(KEY, VALUE, ttl=60))
    assert stored_keys(backend) == [f"demo:{KEY}"]
    raw = asyncio.run(backend.get(f"demo:{KEY}"))
    assert raw is not None
    assert json.loads(raw) == VALUE


def test_second_app_cannot_read_first_apps_key(
    backend: Backend, write_manifest: ManifestWriter, tmp_path: Path
) -> None:
    config.load(write_manifest(tmp_path / "alpha", name="alpha"))
    asyncio.run(get_cache().set("k", 1, ttl=60))
    config.load(write_manifest(tmp_path / "beta", name="beta"))
    assert asyncio.run(get_cache().get("k")) is None
    asyncio.run(get_cache().set("k", 2, ttl=60))
    assert asyncio.run(backend.get("alpha:k")) == "1"
    assert asyncio.run(backend.get("beta:k")) == "2"
    assert stored_keys(backend) == ["alpha:k", "beta:k"]


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 9, 9, tzinfo=UTC),
        {"when": datetime(2026, 9, 9, tzinfo=UTC)},
        {1, 2},
        object(),
        MappingProxyType({"a": 1}),
        b"bytes",
        float("nan"),
    ],
)
def test_non_json_value_raises_and_stores_nothing(
    demo: None, caplog: pytest.LogCaptureFixture, value: object
) -> None:
    assert issubclass(CacheValueError, TypeError)
    with caplog.at_level(logging.INFO, logger="insights.audit"), pytest.raises(CacheValueError):
        asyncio.run(get_cache().set(KEY, value, ttl=60))  # type: ignore[arg-type]
    assert asyncio.run(get_cache().get(KEY)) is None
    assert audit_records(caplog, "cache.set") == []


@pytest.mark.parametrize(
    ("ttl", "error"),
    [(0, ValueError), (-5, ValueError), (True, TypeError), (1.5, TypeError), ("60", TypeError)],
)
def test_ttl_must_be_a_positive_int(demo: None, ttl: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        asyncio.run(get_cache().set(KEY, 1, ttl=ttl))  # type: ignore[arg-type]
    assert asyncio.run(get_cache().get(KEY)) is None


def test_set_and_delete_are_audited_by_hash_and_reads_are_not(
    backend: Backend, demo: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        asyncio.run(get_cache().set(KEY, VALUE, ttl=60))
        asyncio.run(get_cache().get(KEY))
        asyncio.run(get_cache().delete(KEY))
    events = [r.getMessage() for r in caplog.records if r.name == "insights.audit"]
    assert events == ["cache.set", "cache.delete"]
    [set_record] = audit_records(caplog, "cache.set")
    assert set_record["key_sha256"] == KEY_SHA256
    assert set_record["ttl"] == 60
    [delete_record] = audit_records(caplog, "cache.delete")
    assert delete_record["key_sha256"] == KEY_SHA256
    for text in (str(set_record), str(delete_record)):
        assert "E001" not in text
        assert "salary-secret" not in text


def test_hits_counter_counts_hit_and_miss(
    backend: Backend, demo: None, hits: InMemoryMetricReader
) -> None:
    async def scenario() -> None:
        store = get_cache()
        await store.get(KEY)
        await store.set(KEY, VALUE, ttl=60)
        await store.get(KEY)
        await store.get(KEY)

    asyncio.run(scenario())
    assert hit_counts(hits) == {"miss": 1, "hit": 2}


def test_spans_carry_backend_and_result_only(
    backend: Backend, demo: None, spans: InMemorySpanExporter
) -> None:
    async def scenario() -> None:
        store = get_cache()
        await store.set(KEY, VALUE, ttl=60)
        await store.get(KEY)
        await store.get("employee:E999")
        await store.delete(KEY)

    asyncio.run(scenario())
    finished = spans.get_finished_spans()
    assert [s.name for s in finished] == ["cache.set", "cache.get", "cache.get", "cache.delete"]
    assert all(s.kind is SpanKind.CLIENT for s in finished)
    attrs = [dict(s.attributes or {}) for s in finished]
    assert all(a["cache.backend"] == backend.name for a in attrs)
    assert [a.get("cache.result") for a in attrs] == [None, "hit", "miss", None]
    assert {key for a in attrs for key in a} == {"cache.backend", "cache.result"}
    for span in finished:
        assert "E001" not in span.to_json()
        assert "E999" not in span.to_json()
        assert "salary-secret" not in span.to_json()


def test_memory_entries_expire_after_ttl(demo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    store = MemoryCache(clock=lambda: now[0])
    monkeypatch.setattr(cache, "_build_backend", lambda: store)
    asyncio.run(get_cache().set(KEY, 1, ttl=30))
    now[0] += 29
    assert asyncio.run(get_cache().get(KEY)) == 1
    now[0] += 1
    assert asyncio.run(get_cache().get(KEY)) is None
    assert stored_keys(store) == []


def test_memory_evicts_least_recently_used_beyond_maxsize() -> None:
    store = MemoryCache(maxsize=2, clock=lambda: 0.0)

    async def scenario() -> None:
        await store.set("a", "1", ttl=60)
        await store.set("b", "2", ttl=60)
        assert await store.get("a") == "1"
        await store.set("c", "3", ttl=60)
        assert await store.get("b") is None
        assert await store.get("a") == "1"
        assert await store.get("c") == "3"

    asyncio.run(scenario())
    assert stored_keys(store) == ["a", "c"]


def test_redis_applies_ttl_as_key_expiry(demo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "_build_backend", lambda: RedisCache(client))
    asyncio.run(get_cache().set(KEY, 1, ttl=60))
    assert 0 < asyncio.run(client.ttl(f"demo:{KEY}")) <= 60


def test_redis_from_url_sets_mandatory_timeouts_and_decodes_responses() -> None:
    store = RedisCache.from_url("redis://cache.example:6380/2")
    kwargs = store.client.connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"]) == ("cache.example", 6380, 2)
    assert kwargs["socket_timeout"] == 10
    assert kwargs["socket_connect_timeout"] == 10
    assert kwargs["decode_responses"] is True
    asyncio.run(store.aclose())


def test_backend_follows_cache_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cache.CACHE_URL_ENV, raising=False)
    assert isinstance(cache._build_backend(), MemoryCache)
    monkeypatch.setenv(cache.CACHE_URL_ENV, "")
    assert isinstance(cache._build_backend(), MemoryCache)
    monkeypatch.setenv(cache.CACHE_URL_ENV, "redis://cache.example:6380/2")
    store = cache._build_backend()
    assert isinstance(store, RedisCache)
    assert store.client.connection_pool.connection_kwargs["host"] == "cache.example"
    asyncio.run(store.aclose())


def test_get_cache_is_one_per_process_until_reset(demo: None) -> None:
    first = get_cache()
    assert first is get_cache()
    reset_cache()
    assert get_cache() is not first


def test_reset_cache_closes_the_backend_and_drops_the_instance(
    backend: Backend, demo: None
) -> None:
    asyncio.run(get_cache().set(KEY, 1, ttl=60))
    reset_cache()
    assert cache._cache is None
    if isinstance(backend, MemoryCache):
        assert stored_keys(backend) == []
    else:
        assert isinstance(backend, RedisCache)
        assert isinstance(backend.client, ClosingFake)
        assert backend.client.closed


def test_testing_plugin_unsets_cache_url_and_resets_the_cache() -> None:
    assert cache.CACHE_URL_ENV not in os.environ
    assert cache._cache is None


def test_cached_computes_once_then_serves_hits(
    backend: Backend, demo: None, hits: InMemoryMetricReader, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="insights.audit"):
        first = asyncio.run(lookup("E001"))
        second = asyncio.run(lookup("E001"))
    assert first == second == {"id": "E001", "detail": False}
    assert calls == [("E001", False)]
    assert hit_counts(hits) == {"miss": 1, "hit": 1}
    [record] = audit_records(caplog, "cache.set")
    assert record["ttl"] == 60
    assert "E001" not in str(record)
    [key] = stored_keys(backend)
    assert re.fullmatch(rf"demo:{re.escape(lookup.__module__)}\.lookup:[0-9a-f]{{64}}", key)


def test_cached_key_binds_arguments_by_signature(demo: None) -> None:
    asyncio.run(lookup("E001"))
    asyncio.run(lookup(employee_id="E001", detail=False))
    asyncio.run(lookup("E001", detail=True))
    asyncio.run(lookup("E002"))
    assert calls == [("E001", False), ("E001", True), ("E002", False)]


def test_cached_none_result_is_recomputed_and_never_stored(backend: Backend, demo: None) -> None:
    assert asyncio.run(nothing(1)) is None
    assert asyncio.run(nothing(1)) is None
    assert calls == [(1,), (1,)]
    assert stored_keys(backend) == []


def test_cached_non_json_result_raises(demo: None) -> None:
    with pytest.raises(CacheValueError, match="datetime"):
        asyncio.run(stamp(1))


def test_cached_non_json_argument_raises_before_calling(demo: None) -> None:
    with pytest.raises(CacheValueError, match="arguments"):
        asyncio.run(lookup(object()))  # type: ignore[arg-type]
    assert calls == []


def test_cached_concurrent_misses_both_compute_because_there_is_no_lock(demo: None) -> None:
    async def scenario() -> list[int]:
        return list(await asyncio.gather(slow_square(3), slow_square(3)))

    assert asyncio.run(scenario()) == [9, 9]
    assert calls == [(3,), (3,)]


def test_cached_wraps_async_def_only() -> None:
    with pytest.raises(TypeError, match="async def"):

        @cached(ttl=60)
        def sync_fn() -> int:  # type: ignore[type-var]
            return 1


def test_cached_validates_ttl_at_decoration() -> None:
    with pytest.raises(ValueError, match="positive"):
        cached(ttl=0)
    with pytest.raises(TypeError, match="int"):
        cached(ttl=True)


def test_cached_preserves_the_wrapped_function_metadata() -> None:
    assert lookup.__name__ == "lookup"
    assert lookup.__wrapped__ is not lookup  # type: ignore[attr-defined]
