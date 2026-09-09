# Backlog

Platform work beyond the graded submission. `NEXT.md` is the submission's list of deliberate
omissions and their triggers; this file is the build plan for the platform as a product. Each epic
names the ADR it changes, because SCOPE rule 1 still holds: if a change alters an ADR's argument,
the ADR moves first.

**Scope tension, stated once.** The brief scores prioritization and asks for deliberately trivial
apps. Everything below except E0 is post-submission work. If the live session is the near-term goal,
land E0 (it repairs a claim the ADRs already make) and leave the rest here.

**Async I/O throughout.** Every I/O seam the platform owns is async: `AsyncEngine` and
`AsyncSession`, `httpx.AsyncClient`, `redis.asyncio`, `async def` routes, services, repositories,
and job entrypoints. There is one API, not a sync and an async one — ADR-0001's compat surface must
stay enumerable. This lands as EA before anything else is built on the data seam.

Sizes: S ≤ half a day, M 1–2 days, L 3–5 days, XL more than a week.

## What already exists (so the backlog starts from the right place)

Snapshot at the start of the backlog (2026-09-09, before wave 1). The Status column in the
Sequence table tracks what has landed since; the rows below are not updated.

| Area | Have | Missing |
|------|------|---------|
| Auth | `create_app()` installs SSO middleware and the `enforce` dependency before any route (`web.py:34`); boot refuses unmarked routes; every denial audited | Real IdP behind `sso.principal_from_headers`; roles/teams from a directory |
| Async | FastAPI routes may already be `async def`; the testing plugin drives the ASGI app | The data seam is sync (`Engine`, `httpx.Client`); `run_job` takes a sync callable; templates and example apps are sync |
| Database | `get_engine("warehouse")` → SQLAlchemy `Engine`; credentials by name from env; mandatory timeouts with `postgresql` connect timeout already mapped; sqlite fixture seed; audit hook per statement | `psycopg` dependency and a compose `postgres`; an **owned** per-app database with migrations; a session dependency; audited writes |
| Sensitive data | Schema-only logger (`TypeError` on non-scalar, `ValueError` on reserved keys); audit records carry a SHA-256 of SQL and host+path only; no connection strings in app code; pre-commit scans staged files for leaked keys; `require_team` on `/comp`; platform team sees telemetry, not data — ADR-0005 | **Traces carry full SQL text** (`db.statement`) and will carry URL query strings — verified; data classification; TLS enforcement on connections; sensitive-field guard on log keys; real break-glass; retention |
| Caching | — | Everything |
| Frontend | — | Everything |
| Scaffold | `insights new` web/job from `.tmpl` templates; flat `main.py` | Layered backend shape; frontend; per-feature rules |

## Sequence

| # | Epic | Size | Depends on | ADR impact | Status |
|---|------|------|-----------|------------|--------|
| E0 | Scrub SQL text and URL query strings from traces | S | — | ADR-0005 must say traces are telemetry too and how they are scrubbed | Landed #19 |
| EA | Async I/O throughout | M | — | **New ADR-0010 Async I/O**; ADR-0001 compat-surface note | Landed #20 |
| E1 | Postgres for shared connections | S | EA | None (registry is dialect-neutral by design) | Landed #24 |
| E2 | Owned per-app database with migrations | L | EA, E1 | **New ADR-0007 Persistence**; ADR-0004 gains "per-tenant owned stores" | Landed #24 |
| E3 | Backend vertical-slice scaffold and layering rules | M | EA; E2 for a meaningful slice | ADR-0002 (template shape), ADR-0003 (new rules) | Phase A on `wt/slices` (rules, `features/headcount`, `/api/comp`); Phase B (`records` slice, frontend shape) pending |
| E4 | Data classification drives enforcement | M | E3 | **New ADR-0008**; ADR-0005 update | — |
| E5 | Caching layer: in-memory or Redis | M | EA; E4 (classification gates what may be cached) | ADR-0004 (shared Redis, per-tenant namespaces) | Landed #26 (classification gating deferred to E4) |
| E6 | Frontend scaffold for web apps | XL | E3 for the example page | **New ADR-0009 Frontend delivery** | Landed #21 (wave-1 spike) |
| E7 | Break-glass, real | M | E4 | ADR-0005 evidence | — |
| E8 | CLI growth | S each | varies | None | — |

The user's stated priority is the scaffold (E3, E6). E3 needs E2 to generate a slice that persists
anything; E6 is independent of E2/E3 technically and runs as a parallel spike from wave 1.

---

## E0 — Scrub SQL text and URL query strings from traces

**Goal.** No literal from a query or request reaches a trace backend, matching what the audit stream
already promises.

**Why.** Verified: an instrumented query produces a span with
`db.statement = "select base_salary from compensation where employee_id = 'E001'"`. Traces are
telemetry the platform team sees by default. This is a hole in ADR-0005's claim today, not later.

**Design.** A `SpanProcessor` installed by `_otel.build()` that, on span end, replaces
`db.statement` with `sha256:<hex>` (the same hex the audit stream records as `statement_sha256`, so
the two correlate) and rewrites `http.url` / `url.full` on client spans to scheme+host+path and
drops `url.query`. If the SDK's `ReadableSpan` attributes prove immutable at `on_end`, wrap the
exporter instead and rebuild the attribute mapping before export. Collector-side redaction is
documented as belt-and-braces, not the control — an app pointed straight at Tempo must still be clean.

**Acceptance.** Test: run an instrumented query with a literal and an httpx request with a query
string against an in-memory span exporter; assert neither literal appears anywhere in the exported
spans and the hash matches the audit record. ONBOARDING "Know it is healthy" states it.

## EA — Async I/O throughout

**Goal.** One async data seam, one async job runner, async templates and example apps; no sync
data API remains.

**Why.** Web apps are I/O-bound and FastAPI is async-native; a sync engine under async routes blocks
the loop or forces threadpools. Two APIs (sync and async) would double the compat surface ADR-0001
keeps enumerable. Decide once, early, before E2/E3/E5 build on the seam.

**Design.**
- Data: `get_engine(name) -> sqlalchemy.ext.asyncio.AsyncEngine` (`sqlite+aiosqlite://` for
  fixtures, `postgresql+psycopg://` for Postgres — psycopg 3 serves both sync and async, one driver);
  `get_http_client(name) -> httpx.AsyncClient`; `get_connection(name)` returns the union.
  Construction stays sync (it builds objects, it does no I/O); `validate_connections()` stays sync
  and runs at boot; new `async ping_connections()` does `SELECT 1` / a HEAD request with the
  mandatory timeout, used by `/readyz`.
- The five things construction owns are attached to the async objects: audit via
  `event.listen(engine.sync_engine, "before_cursor_execute", …)`; OTel via
  `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)` and
  `HTTPXClientInstrumentor().instrument_client(async_client)`; timeouts unchanged; fixture seeding
  runs once, synchronously, before the async engine is first used; `httpx.MockTransport` handlers
  work unchanged under `AsyncClient`.
- Jobs: `run_job(fn: Callable[[], Awaitable[object]], *, manifest=None) -> int` runs `fn()` under
  `asyncio.run` inside the span; context set before `asyncio.run` is visible inside the task.
- Web: template routes are `async def`; `async with get_engine(...).connect() as conn:
  result = await conn.execute(...)`. `/readyz` awaits `ping_connections()`.
- Testing plugin: `client_for(app)` keeps `TestClient` (it drives the async app on its own loop);
  `reset_clients()` stays sync and disposes async engines via `sync_engine.dispose()` and closes
  async clients on a short-lived loop.
- Rules: `no-client-construction` already lists `create_async_engine` and `httpx.AsyncClient`;
  `no-raw-drivers` adds `aiosqlite`.
- Dependencies: `sqlalchemy[asyncio]` (pulls `greenlet`), `aiosqlite`. `.env.example` and compose
  URLs switch to `sqlite+aiosqlite://`.
- Example apps and both templates are rewritten async; ONBOARDING/README snippets follow.

**Acceptance.** All SDK tests green; both example apps green and running under compose with async
routes; the job runs an `async def main()`; `insights check` clean; `pytest sdk apps` in one
session green; fresh clone passes the README.

**ADR-0010 Async I/O** (new): one async seam. Alternatives: sync-only with threadpool offload;
dual sync/async APIs; async only for HTTP and sync for SQL.

## E1 — Postgres for shared connections

**Goal.** `warehouse` can be a real Postgres in compose while tests stay on sqlite.

**Design.** Add `psycopg[binary]`; compose `postgres` service under a `postgres` profile with an init
script that applies `warehouse.sql`; `.env.example` gains a commented `postgresql+psycopg://` URL.
SDK-side seeding stays gated on the sqlite backend — a Postgres database is never seeded by an app
process (seeding is the fixture's job, not the SDK's). Registry already maps `connect_timeout`; add
`sslmode=require` when the host is not local (moves to E4 if it needs classification context).

**Acceptance.** `docker compose --profile postgres up`; web app reads `/comp` from Postgres;
`uv run pytest` unchanged on sqlite; `insights check` unchanged.

## E2 — Owned per-app database with migrations

**Goal.** A web app can persist its own state in a database it owns, with schema migrations, without
constructing an engine or writing a connection string.

**Why.** The brief's "interactive CRUD web apps" have nowhere to write today. Owned stores are a
per-tenant resource, so they belong under ADR-0004's isolation line: per-app credentials, per-app
database or schema, platform-owned construction.

**Design.**
- `platform.toml`: `[database] enabled = true`. `manifest-valid` learns the table.
- Env: `INSIGHTS_DB_URL` (per app, its own role and database; compose init creates both).
- SDK `insights_platform.db`: `get_engine() -> AsyncEngine` for the owned DB (same construction
  path as connections: timeouts, audit, OTel, TLS), `get_session()` FastAPI dependency yielding an
  `AsyncSession`, `Base` declarative base. Writes audited as `data.write{table, rows}` — table name
  and count, never values.
- Migrations: Alembic scaffolded into `apps/<name>/migrations/` with an async `env.py`
  (`run_async_migrations`) reading `INSIGHTS_DB_URL` from the SDK, autogenerate from the app's
  models. `insights db revision -m …`, `insights db upgrade`, `insights db current` wrap Alembic so
  no app touches `alembic.ini`.
- Tests: the testing plugin provides an owned `sqlite+aiosqlite` DB per test with
  `Base.metadata.create_all` via `run_sync`; an `integration` marker runs against compose Postgres.
- Rules: `no-client-construction` already covers `create_engine`/`create_async_engine`; add
  `no-raw-alembic` (apps do not import `alembic` directly; the CLI does).

**Acceptance.** `insights new x --kind web` with `[database] enabled = true` → `insights db upgrade`
creates the schema in compose Postgres; a generated feature writes and reads a row; the audit
stream shows `data.write{table="records", rows=1}` and no values; tests pass on sqlite.

**ADR-0007 Persistence** (new): owned stores are per-app Postgres databases behind SDK-constructed
async engines; shared stores stay read-only connections. Alternatives: one shared database with
schemas per app; app-managed connection strings; no owned persistence (apps call APIs only).

## E3 — Backend vertical-slice scaffold and layering rules

**Goal.** A generated web app has a recognisable, layered shape, and the platform checks that the
layers stay in order — the "architecture tests for apps" idea from day one.

**Design.** Template `src/<pkg>/`:

```
main.py                      create_app(); include each feature's router under /api
features/
  records/                   one generated example slice, all async
    router.py                HTTP surface; imports service, schemas only
    service.py               use cases; imports repository, models, schemas
    repository.py            queries against the owned AsyncSession; imports models
    models.py                SQLAlchemy models (owned DB, E2)
    schemas.py               Pydantic request/response models
```

Django mapping for readers who know it: `router.py` ≈ views + urls, `schemas.py` ≈ serializers,
`models.py` ≈ models, `repository.py` ≈ managers/querysets, `service.py` ≈ the business logic
Django leaves to you.

New `insights check` rules (ADR-0003):
- `slice-layering`: within a feature, `router` → `service`/`schemas`; `service` →
  `repository`/`models`/`schemas`; `repository` → `models`; nothing imports `router`.
- `features-independent`: a feature imports another feature only through its `__init__` (the EMES
  "handlers do not depend on each other" rule, transplanted).
- `api-prefix`: routers are included under `/api` (frontend contract, E6).

Jobs keep a flat `main.py` with `async def main()`; a job with more than one module gets `steps/`
and no rules.

**Acceptance.** Generated app passes all rules; a fixture that imports `repository` from `router`
fails `slice-layering` with an ADR-cited message; `apps/people-analytics-comp` is restructured into a
`comp` feature; ONBOARDING gains "Shape of a web app".

## E4 — Data classification drives enforcement

**Goal.** The platform knows which data is sensitive and refuses the obviously wrong thing at the
point of construction, where it already stands.

**Design.**
- Registry: each `ConnectionSpec` gains `classification` (`public | internal | confidential |
  restricted`); `warehouse` is `restricted`. Owned databases inherit the app's declared
  classification from `platform.toml` (`[app] data_classification`).
- Enforcement at `get_connection()` / `db.get_engine()`: a `restricted` connection requested during a
  request whose matched route is `@public` raises `ClassificationError` and audits it. The SDK
  already has the route's policy in `request.scope["endpoint"]`.
- TLS: `sslmode=require` for non-local Postgres; `https` required for non-`.fixture` HTTP hosts;
  refused at construction otherwise.
- Log-field guard: a denylist of key names (`ssn`, `salary`, `base_salary`, `dob`, `email`,
  `token`, `password`) raises `ValueError` unless the value is wrapped `Redacted(...)`, which logs
  its hash. Keeps ONBOARDING's "a salary is a number" honest with tooling.
- Secrets: connection tokens held as `SecretStr`; never in `repr` or exceptions.
- Retention: audit stream retention and export path documented; a `restricted` app's audit stream
  is retained longer.

**Acceptance.** `@public` route calling `get_engine("warehouse")` → 500 in the app,
`classification.denied` in audit, test proves it; `get_logger(...).info("x", salary=100)` raises;
Postgres URL to a non-local host without TLS refused.

**ADR-0008** (new): classification lives in the registry and manifest, and construction enforces it.
Alternatives: policy in review only; tagging at the data warehouse; DLP at the network edge.
ADR-0005 update: traces are telemetry, scrubbed (E0); classification is what break-glass (E7) keys on.

## E5 — Caching layer: in-memory or Redis

**Goal.** Apps cache through one seam that the platform constructs, namespaces, and instruments.

**Design.**
- `insights_platform.cache.get_cache() -> Cache`; async protocol `await get(key)`,
  `await set(key, value, *, ttl)`, `await delete(key)`; `ttl` is required. `@cached(ttl=…)` wraps
  async service functions.
- Backends: `MemoryCache` (per process, LRU with TTL) by default; `RedisCache` on `redis.asyncio`
  when `INSIGHTS_CACHE_URL` is set (dependency `redis`); keys are prefixed `<app>:` — the ADR-0004
  isolation line applied to a shared Redis, with per-app ACL users as the trigger for stronger
  separation.
- Values are JSON only. No pickling: this blocks caching ORM rows or arbitrary objects by accident
  and keeps the seam vendor-neutral.
- Classification (E4): caching data from a `restricted` connection requires `ttl <= 300` and an
  explicit `classification="restricted"` argument, audited as `cache.set{classification}`.
- Metrics: `insights.cache.hits{result}` counter. compose `redis` under a `cache` profile.
- Rules: `no-raw-drivers` extends to `redis`, `aioredis`, `memcache`.

**Acceptance.** Same tests pass with both backends via the testing plugin; a second app cannot read
the first app's key; caching a restricted result without the explicit argument raises.

## E6 — Frontend scaffold for web apps

**Goal.** `insights new x --kind web` produces a backend and a React frontend that runs against it
locally and ships in one container.

**Design.**
- `apps/<name>/frontend/`: Vite + React + TypeScript; `src/components/`, `src/pages/`,
  `src/api/client.ts` (typed fetch to `/api/*`, same-origin), `src/main.tsx`, `index.html`,
  `package.json`, `tsconfig.json`, `vite.config.ts`, `eslint.config.js`.
- Dev: Vite dev server proxies `/api` to `:8000` and injects `X-Insights-*` headers from
  `frontend/.env.local` so the SSO stub works without a proxy. Prod: the SSO proxy injects headers.
- Serve: `insights_platform.frontend.mount_frontend(app)` mounts `frontend/dist` with
  `StaticFiles(html=True)` at `/` when the directory exists. It must run **after** every route is
  registered — a `Mount("/")` registered first would shadow them — so `create_app()` calls it from
  the platform lifespan, next to `check_routes`. Routers live under `/api` (E3's `api-prefix`
  rule). `/healthz`, `/readyz` unchanged.
- Build: Dockerfile becomes multi-stage (node build → Python image copies `dist`); `.dockerignore`
  adds `**/node_modules`.
- CI: `app-check.yml` adds a `frontend` job when `frontend/package.json` exists — `setup-node`,
  `npm ci`, `eslint`, `tsc --noEmit`, `vite build`, `vitest run`. Pre-commit: `eslint` and
  `prettier` as local hooks scoped to `apps/*/frontend/`.
- Scaffold flag: `--no-frontend` for API-only web apps. Jobs never get one.
- Generated example: a `Records` page listing `/api/records` from E3's slice, with a component test
  (Vitest + Testing Library).

**Acceptance.** Fresh clone → `insights new`, `npm ci`, `npm run dev` shows the page against the
running backend; `docker compose up` serves the built page at `/`; CI frontend job green; a
frontend lint error fails the app's PR.

**ADR-0009 Frontend delivery** (new): a co-located SPA served by its own app under `/`, API under
`/api`. Alternatives: separate frontend service and image; server-side rendering; a shared portal
that hosts every app's UI (this is the self-service portal in NEXT.md — different trigger).

## E7 — Break-glass, real

**Goal.** ADR-0005's break-glass is an implemented, evidenced path instead of a stub.

**Design.** `insights breakglass grant --app X --minutes N --reason "…" --approver <id>` writes
`breakglass.granted{operator, app, minutes, reason, approver}` to the audit stream and issues a
signed, time-boxed token; `get_connection()` honours it only for that operator principal and only
against that app's connections, auditing every access as `data.query{breakglass=true}`;
`insights breakglass revoke`; `insights audit tail --app X` gives the tenant the read view ADR-0005
promises. Approval remains a recorded field until an approval system exists.

**Acceptance.** Grant → access → audit trail shows grant, each access, expiry; expired token
refused; tenant can list it.

## E8 — CLI growth

Small items, each S: `insights db …` (E2); `insights check --format json`; `insights new --force`;
`insights new` running `uv sync`; `insights new --no-frontend` (E6); `insights upgrade` stays in
`NEXT.md` with its trigger.

## Cross-cutting

- compose profiles: `postgres`, `redis`, `observability` (the LGTM stack from NEXT.md becomes
  attractive once E0 makes traces safe to look at).
- ONBOARDING sections: "Shape of a web app" (E3), "Your database" (E2), "Caching" (E5), "The
  frontend" (E6), "Sensitive data" (E4). Coordinator-owned; written after each wave merges.
- CI time: the node job roughly doubles per-app CI; path-filter it to `frontend/**` changes plus SDK
  changes.
- Every new construction path (owned DB, cache, frontend proxy) gets the same five things
  `get_connection()` owns today: credentials by name, mandatory timeouts, audit, OTel, fixture
  routing — and a fixture so `uv sync && uv run pytest` stays true from a clean clone.

---

## Execution plan

Three waves of parallel worktrees. Boundaries are file-ownership lists; contracts are the
signatures every agent implements against so parallel work does not collide. Anything not in an
agent's list is off-limits except a small additive edit it reports. Docs (`README.md`,
`ONBOARDING.md`, `NEXT.md`, this file) are coordinator-owned and updated after each wave merges.

### Wave 1 — parallel: E0, EA, E6-spike — landed 2026-09-09 (#19, #20, #21)

**E0 `wt/trace-scrub`** owns `sdk/src/insights_platform/observability/_otel.py`, additive edits to
`observability/__init__.py`, new `sdk/tests/test_trace_scrub.py`.
Contract: `ScrubbingSpanProcessor` installed by `_otel.build()` ahead of exporters;
`db.statement → "sha256:<hex>"` (hex identical to the audit `statement_sha256`); `http.url` /
`url.full → scheme://host/path`; `url.query` removed.

**EA `wt/async-io`** owns `sdk/src/insights_platform/data/**`, `job.py`, `web.py`,
`testing/__init__.py`, `check/rules/no_raw_drivers.py`, `sdk/pyproject.toml` (dependencies only),
`templates/web/src/**`, `templates/web/tests/**`, `templates/job/**`, `apps/*/src/**`,
`apps/*/tests/**`, `.env.example`, `docker-compose.yml` (URL schemes only),
`sdk/tests/{test_data,test_job,test_web,test_testing}.py`, and a DRAFT `docs/adr/0010-async-io.md`.
Contract:

```python
# insights_platform.data
def get_engine(name: str) -> sqlalchemy.ext.asyncio.AsyncEngine
def get_http_client(name: str) -> httpx.AsyncClient
def get_connection(name: str) -> AsyncEngine | httpx.AsyncClient
def validate_connections() -> None            # construction only; boot
async def ping_connections() -> None          # SELECT 1 / HEAD with the mandatory timeout; /readyz
def reset_clients() -> None                   # sync, safe between tests
# insights_platform.job
def run_job(fn: Callable[[], Awaitable[object]], *, manifest: Path | None = None) -> int
# insights_platform.testing — unchanged: headers_for(...), client_for(app) (TestClient)
# templates: `async def` routes; `async with get_engine("warehouse").connect() as conn:`
#            `result = await conn.execute(text(...))`; job `async def main()`.
```

**E6 `wt/frontend`** owns `sdk/src/insights_platform/frontend.py` (new), `templates/web/frontend/**`
(all `.tmpl`), `templates/web/Dockerfile.tmpl`, `templates/web/README.md.tmpl`, `cli/new.py`
(`--no-frontend`), `sdk/tests/test_frontend.py`, additions to `sdk/tests/test_cli.py`,
`.github/workflows/app-check.yml` (conditional `frontend` job), `.dockerignore`,
`.pre-commit-config.yaml` (eslint/prettier local hooks), a DRAFT `docs/adr/0009-frontend-delivery.md`,
and **one additive line** in `web.py`'s lifespan calling `mount_frontend(app)` after `check_routes`
(reported; coordinator resolves against EA at merge).
Contract: `mount_frontend(app: FastAPI, *, dist: Path | None = None) -> bool` — `dist` defaults to
`<manifest dir>/frontend/dist`; returns whether it mounted. Node must be present on the machine to
verify `npm ci && npm run build`; if it is not, implement and mark verification deferred.

Merge order: E0, EA, then E6 (rebase; resolve the one-line `web.py` overlap). Then regenerate
nothing — the example apps were converted by EA. Fresh-clone check.

### Wave 2 — parallel: E1+E2, E5, E3 (E3 merges last) — E1+E2 #24 and E5 #26 landed 2026-09-09; E3 Phase A on `wt/slices`

**E1+E2 `wt/database`** owns `data/registry.py`, additive `data/__init__.py`, new
`sdk/src/insights_platform/db/**`, `cli/db.py` + registration in `cli/__init__.py`,
`templates/web/migrations/**`, `templates/web/platform.toml.tmpl` (`[database]`),
`check/rules/manifest_valid.py`, new `check/rules/no_raw_alembic.py`, `sdk/pyproject.toml`
(`psycopg[binary]`, `alembic`), `docker-compose.yml` (`postgres` profile + init script under
`compose/postgres/`), `.env.example`, tests, DRAFT `docs/adr/0007-persistence.md`.
Contract: `db.get_engine() -> AsyncEngine`, `db.get_session()` async dependency yielding
`AsyncSession`, `db.Base`; env `INSIGHTS_DB_URL`; `insights db {revision,upgrade,current}`.

**E5 `wt/cache`** owns new `sdk/src/insights_platform/cache/**`, `sdk/tests/test_cache.py`,
`check/rules/no_raw_drivers.py` (add `redis`, `aioredis`, `memcache`), `sdk/pyproject.toml`
(`redis`), `docker-compose.yml` (`redis` profile), `.env.example` (`INSIGHTS_CACHE_URL`).
Contract: `get_cache() -> Cache` with `async get/set/delete`, `ttl` required, JSON values only,
`<app>:` key prefix, `@cached(ttl=…)` for async functions. Classification gating is a follow-up in E4.

**E3 `wt/slices`** owns `templates/web/src/**`, `templates/web/tests/**`, new rules
`slice_layering.py`, `features_independent.py`, `api_prefix.py`, `check/rules/__init__.py`
registration, fixtures under `sdk/tests/fixtures/broken_apps/`, `sdk/tests/test_check.py`
additions, and the restructuring of `apps/people-analytics-comp/**` into a `comp` feature.
Contract: the feature layout above; routers included under `/api`; repositories take an
`AsyncSession` from `db.get_session()` (E2's contract) — E3 builds against it and merges after E2.

Merge order: E1+E2, E5, then E3 (rebase). `sdk/pyproject.toml`, `docker-compose.yml`,
`.env.example`, and `check/rules/__init__.py` will have trivial overlaps — resolve at rebase.
Fresh-clone check including `--profile postgres` and `--profile cache`.

### Wave 3 — E4 then E7; E8 and docs alongside

**E4 `wt/classification`** owns `data/registry.py` (classification), `data/__init__.py` and
`db/**` (enforcement + TLS), `observability/__init__.py` (log-field guard, `Redacted`), an
additive policy-lookup helper in `auth/`, `cache/**` (gating), `check/rules/manifest_valid.py`
(`data_classification`), tests, DRAFT `docs/adr/0008-data-classification.md`.

**E7 `wt/breakglass`** (after E4 merges) owns new `cli/breakglass.py`, `cli/audit.py`, `audit.py`,
additive `data/__init__.py`, tests.

**E8** small CLI items in their own short-lived worktrees as convenient.

Coordinator, after each wave: verify every worktree independently (gates plus a live smoke of the
feature itself), push, PR, merge with merge commits, rebase what remains, fresh-clone the README,
update `ONBOARDING.md`/`README.md`/`NEXT.md`, and record every ADR-relevant fact in `NEXT.md`
"Found during the build" for the author.
