<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0010: Async I/O

**Status:** Proposed · **Date:** 2026-09-09

## Context

Web apps on the platform are I/O-bound and FastAPI is async-native, yet the data seam shipped sync:
`get_engine()` returned a SQLAlchemy `Engine` and `get_http_client()` an `httpx.Client`. A sync
engine under an async route blocks the event loop or is pushed onto a threadpool, and every seam
built next — owned databases, caching, the frontend's API — inherits the choice the data seam made.
ADR-0001 keeps the compatibility surface enumerable; a sync and an async API side by side double it.

## Decision

One async seam. `get_engine()` returns `sqlalchemy.ext.asyncio.AsyncEngine`, `get_http_client()`
returns `httpx.AsyncClient`, routes and job entrypoints are `async def`, and `run_job()` runs
`main()` under `asyncio.run` inside the job span. Construction stays synchronous because it does no
I/O: `validate_connections()` builds every declared connection at boot; `ping_connections()` is the
only awaited check and backs `/readyz`. The five things construction owns — credentials by name,
mandatory timeouts, the audit hook, OpenTelemetry instrumentation, fixture routing — attach to the
async objects through `engine.sync_engine` and `instrument_client()`. No sync data API remains.

## Alternatives considered

**Sync-only with threadpool offload.** FastAPI already runs sync routes on a threadpool, so it costs
nothing today. Rejected: it bounds concurrency by thread count, hides the blocking call behind the
framework, and makes every later seam (sessions, cache, migrations) choose again.

**Dual sync and async APIs.** Lets a script stay sync. Rejected: two client types, two audit hooks,
two instrumentation paths, and two rules to keep them apart — the surface ADR-0001 promises to keep
enumerable doubles, and every release has to prove both.

**Async for HTTP, sync for SQL.** The usual split when an async driver is missing. Rejected: psycopg
3 and aiosqlite each serve sync and async with one driver, so the split buys nothing and leaves the
warehouse — the connection that carries compensation data — on the blocking path.

## Consequences

Apps write `async with get_engine("warehouse").connect() as conn` and `await conn.execute(...)`;
jobs write `async def main()`. Tests keep `TestClient`, which drives the async app on its own loop;
`reset_clients()` disposes on a short-lived loop because aiosqlite closes through its own awaitable
and `sync_engine.dispose()` from plain sync code leaks the connection. `sqlalchemy[asyncio]` pulls
`greenlet` unconditionally. `/readyz` now does I/O — `SELECT 1` and `HEAD /` per connection, each
audited. Plain `sqlite:///` URLs are refused; `.env.example` and compose carry `sqlite+aiosqlite://`.
