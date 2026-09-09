# Next

What was consciously left out, and what would trigger building it. Running list during the build;
cleaned up at the end.

## Deliberate omissions

| Omission | Trigger to build it |
|----------|---------------------|
| Real Kubernetes manifests | First environment that isn't a single compose host |
| Secrets manager integration | First real credential; today every value is a fixture |
| Service mesh | Never at 5–25 tenants on one shared runtime; revisit if tenants leave it |
| Sidecar for the auth, data-access and telemetry seams | A runtime that co-schedules containers — same trigger as real Kubernetes. Then any of: a tenant that is not Python, a security fix that must cross the fleet without 25 team PRs, or enforcement that has to survive an uncooperative app (ADR-0001) |
| Self-service portal UI | ~15 tenants, when scaffold support exceeds an engineer-week per month |
| Multi-region | A tenant with a data-residency requirement |
| `insights upgrade` | ~12 apps, when hand-migrating between scaffold versions is the biggest time sink |
| `insights deploy` | When the compose-based path stops matching how prod actually deploys |
| Grafana / Tempo / Loki compose profile | First time someone needs to look at a trace rather than grep a log; the seam is already OTLP, so this is zero SDK change |
| Circuit breaker / retry policy on connections | First partial outage of a shared source; `get_connection` owns construction, so this lands in one place |
| Static mirror of the route-authZ check | When someone wants it in pre-commit; the runtime boot check is sufficient until then |
| Deprecation shim tooling | First SDK change that cannot land in one PR with all dependents |
| `import-linter` | Considered and rejected: contract config would live outside the SDK package, so rules would not be versioned with the SDK |

## Found during the build

| Finding | Disposition |
|---------|-------------|
| Required log keys (`app`, `team`, `principal`, `request_id`, `trace_id`, `span_id`) are reserved; a caller passing one gets `ValueError`. Auth records the denied caller's team as `principal_team`; break-glass will need its own key for the operator (e.g. `grantee`) | Design note for ADR-0005/0006: say why silent override was rejected |
| `opentelemetry.sdk._logs.LoggingHandler` is deprecated in OTel 1.44 in favour of `opentelemetry-instrumentation-logging` | One dependency plus one import swap in `observability/_otel.py`; three warnings today |
| The OTel exporter adds `code.file.path` / `code.function.name` / `code.line.number` to every record | Harmless; a collector processor can drop them |
| `SQLAlchemyInstrumentor` patches `sqlalchemy.create_engine` globally and rejects a second `instrument()` | Instrumented once in the registry; engines are built through the module attribute so every one is covered |
| Starlette 1.6 deprecates `TestClient` over `httpx` in favour of `httpx2` | No dependency change yet; revisit when `httpx2` stabilises |
| `insights check` does not track local-name shadowing (a parameter named `httpx`) | Accepted as accidental-not-adversarial per ADR-0003 |
| No rule stops an app calling `logging.basicConfig` or reconfiguring the root logger | Candidate eighth rule the first time it bites |
| The SSO stub treats a missing `X-Insights-Team` as `""`, so `require_team` simply denies | A real IdP mapping decides whether team is mandatory |
| Request contextvars leaked between test modules until `sdk/tests/conftest.py` reset them | Fixed; the testing plugin now snapshots and restores them around every test |
| The SDK shipped without a `py.typed` marker, so a consumer's `mypy --strict` saw `insights_platform` as untyped — seven errors on a freshly generated app | Fixed: marker added. The per-app CI job (`mypy <app>/src`) is what catches this class of defect |
| `get_logger("<app package>")` landed outside the `insights` logger the OTel handler is attached to, so an app's own log lines were dropped in production | Fixed (#13): every name is namespaced under `insights.`. Found by running a generated job end to end and noticing `rollup.completed` never appeared |
| `pytest_plugins` is only honoured in rootdir conftests, so apps could not opt into the testing plugin per directory | Registered as a `pytest11` entry point instead; templates ship no conftest; the plugin also loads into the SDK's own test session |
| Once counters had data, OTel's atexit metric flush wrote to pytest's already-closed capture stream | Fixed: the plugin shuts OTel down in `pytest_sessionfinish`; any other test process that calls `configure()` needs the same |
| `observability.configure()` is once per process (first app wins) and `context.app` follows the last `config.load()` | By design: one app per process. CI runs `pytest apps/<x>` per app and root `testpaths` stays `sdk/tests` |
| `run_job` flushes OTel rather than shutting it down | Global-once providers cannot be rebuilt mid-session; OTel's own atexit handler does the real shutdown in production |
| `insights_platform.testing` imports `pytest`, a dev-group dependency | Harmless at runtime (apps never import it); an `[project.optional-dependencies] testing` extra would be cleaner |
| `insights new` echoes `--dest` as given, has no `--force`, and does not run `uv sync` for you; `insights check` has no `--format json` | Add when someone asks |
| Template test import order relies on ruff classifying app packages as third-party | If `apps/*/src` is ever added to ruff `src`, have `insights new` run `ruff check --fix --select I` on its output |
| `uv` silently drops a declared version constraint when `[tool.uv.sources]` maps the dependency to a workspace member: an app declaring `insights-platform>=9,<10` against a local `0.1.0` locks and installs `0.1.0`, and the lockfile records `editable` with no specifier | The pin is a contract the workspace cannot enforce, so `sdk-pin-declared` enforces it (ADR-0001). Built images resolve from the index, where the pin is real |
| The fresh-clone test failed on Windows: fixture paths reach 114 characters, and a clone 151 characters deep crossed `MAX_PATH`, so checkout stopped partway and `uv run pytest` found no tests | Documented in the README; shorten the fixture app names if a second person hits it |
| Traces carried the full SQL text in `db.statement` and request URLs with their query strings, while the audit stream only ever recorded a hash — verified before E0 | Fixed (#19): `ScrubbingSpanProcessor` wraps the exporting processor; SQL text becomes the same SHA-256 the audit stream records, URLs lose query, fragment and userinfo. ADR-0005 needs the sentence that traces are telemetry too and how they are scrubbed |
| `ReadableSpan` attributes are frozen before any processor's `on_end` runs (`Span.end()` sets `BoundedAttributes._immutable`), so a processor cannot scrub in place | The scrubber rebuilds the span through `ReadableSpan`'s constructor. Scrubbing is structural: only processors inside the wrapper see clean spans, and a test pins that |
| SQLAlchemy instrumentation writes `str(exception)` into the span status description and exception events, so a database error message can echo a literal | Not scrubbed yet; revisit when Postgres (E1) makes error text realistic |
| `pre-commit run --all-files` skips untracked files; the commit hook caught a credential-shaped test URL the gate had passed | Stage new files before running the gate |
| The data seam is async only: `get_engine()` returns `AsyncEngine`, `get_http_client()` returns `httpx.AsyncClient`, `run_job()` takes a coroutine function (#20, ADR-0010 draft) | ADR-0001's compatibility-surface list should say the data interface is one async API, not a sync and an async one |
| `sync_engine.dispose()` from plain sync code on an aiosqlite pool raises `MissingGreenlet` and leaks the connection | `reset_clients()` awaits `engine.dispose()` on a short-lived loop; BACKLOG's design note was wrong on this point |
| `/readyz` now does I/O (`SELECT 1`, `HEAD /`) and writes `data.query` / `data.request` audit records on every probe; compose polls every 10 s | Accepted; give the probe its own event name or sample it if audit volume matters |
| A plain `sqlite:///` URL is refused once the engine is async; `sqlite+aiosqlite://` is required, so a stale `.env` fails at boot and at `/readyz` | `.env.example` and compose carry the new scheme; the error names the missing driver |
| `SQLAlchemyInstrumentor.instrument()` (0.65b0) also wraps `create_async_engine`, so the single global call still covers every engine | No change; the earlier row stays true |
| The web template's routes moved under `/api` in wave 1, ahead of E3, because a `GET /` route would shadow the SPA mounted at `/` | Design note for ADR-0009 and E3's `api-prefix` rule; the example apps keep `/comp` until E3 restructures them |
| The static frontend mount is not an `APIRoute`: `check_routes` ignores it and no authorization marker applies to assets, so the page shell is public and only `/api` is protected | Stated in the ADR-0009 draft; ADR-0005 may want the same sentence |
| `StaticFiles(html=True)` serves `index.html` at `/` only, so client-side deep links return 404 | Add a fallback when the first app needs client routing |
| Static-asset requests are labelled `unmatched` in `insights.http.requests` | Label them `static` when someone reads that counter |
| `npm ci` needs a lockfile, so the SDK ships `package-lock.json.tmpl` (132 KB) with exact-pinned versions; `detect-secrets` flags its integrity hashes | The hook excludes `package-lock.json`; TypeScript stays on 6.0.x because `typescript-eslint` declares a `<6.1` peer |
| `--no-frontend` needs conditional structure that `__NAME__` substitution does not have (ADR-0002) | `frontend/**` is skipped and `<file>.no-frontend.tmpl` replaces `<file>.tmpl` for the Dockerfile and README; ADR-0002's "more than a name" trigger has fired in a small way |
| Per-app CI grows by node setup plus `npm ci` (about 40 s) when a frontend exists, and `ci.yml` does not yet path-filter to `frontend/**` | BACKLOG cross-cutting item; do it when CI time bites |
| A generated app cannot be built into an image until `uv sync` has added it to `uv.lock`, because the Dockerfile runs `uv sync --frozen` | Pre-existing; ONBOARDING's "run `uv sync`" step covers it |
| The owned database shares its construction with the warehouse (`data/_engine.py`): URL by name from env, timeouts, `data.query` hash per statement, OTel; every flush adds `data.write{connection, table, rows}` from a sync `after_flush` listener | ADR-0004 needs the sentence "per-tenant: an owned database with its own role, reached only through `INSIGHTS_DB_URL`"; ADR-0007 draft written |
| Two schema paths on purpose: on SQLite `db.validate()` creates the schema from the models at boot; Postgres is only ever changed by `insights db upgrade`. A unit test therefore cannot prove a migration | The `integration` marker runs against compose Postgres; skipped otherwise |
| FastAPI 0.141 closes yield-dependencies after the response is sent, so `get_session()` commits after the client has its 201 | Repositories flush inside the route when they need a generated id or want a constraint error as a 500; ADR-0007 consequences say so |
| psycopg's async connection refuses Windows' default `ProactorEventLoop` | `insights db` switches to the selector policy on win32; uvicorn on Windows cannot reach Postgres — use SQLite or compose |
| `alembic` must be ≥ 1.16: `path_separator = os` exists only from there, otherwise `prepend_sys_path` splits `C:\` on `:` | Pinned |
| `insights db` imports the app so autogenerate sees its models, which boots `create_app()`: one upgrade prints about six `data.query` lines, a span and a metrics blob | Accepted; a quiet mode is a CLI item for E8 |
| `insights db upgrade` on SQLite fails with "unable to open database file" when the URL's parent directory does not exist (fresh clone, `.local/` absent), because Alembic's `env.py` builds the engine without the `mkdir` that `validate()` does | Create the SQLite parent directory in engine construction, as the warehouse path does |
| The owned Postgres role can still `CONNECT` to the warehouse database (`CONNECT` is granted to `PUBLIC` by default) although it cannot read its tables | Harden `compose/postgres/20-owned-databases.sh` with `revoke connect on database … from public` |
| Cache isolation is the key prefix `<app>:`, evaluated per call from the loaded manifest; two apps on one Redis cannot read each other's keys, but nothing stops a mis-set URL | Per-app Redis ACL users are the stronger step and the trigger for it |
| `redis.asyncio` connections are loop-bound: closing the client on a fresh loop after real use raises "Event loop is closed" and leaks the transport | Apps never call `reset_cache()`; a production shutdown wants an in-loop `aclose()` in the web lifespan and `run_job` |
| `@cached` has no lock, so concurrent misses both compute; `None` results are never stored because `None` reads back as a miss | Documented; a lock is a follow-up if a hot key ever matters |
| `fakeredis` subclasses `redis.asyncio.Redis`, so the cache tests exercise redis-py's real command encoding (`SET … EX`) without a server | Dev dependency, justified |
| `check/core.py` now resolves relative imports to absolute names against the file's package; the old comment that no rule could apply to them was true only before slice rules existed | On `wt/slices`; absolute-prefix rules unaffected, a test pins it |
| `features-independent` checks the module named in the import statement, so `from ..b import service` passes: submodule versus re-export is undecidable statically | ADR-0003's "static catches accidental, not adversarial" applies |
| `api-prefix` reads only literal paths and prefixes and `APIRouter(prefix=)` built in the same module; routes on objects it cannot trace to `create_app()` are ignored and non-literal prefixes are reported as unreadable | On `wt/slices`; same ADR-0003 placement argument |
| E3 restructures `apps/people-analytics-comp` into a `comp` feature: `/comp` becomes `/api/comp` and `GET /` is dropped because the SPA contract owns `/`; the README curls change when it merges | On `wt/slices`, Phase A verified; Phase B (the owned-DB `records` slice and the frontend shape) pending |
| The browser needs an SSO stub too: the template relies on the Vite dev proxy and `.env.local`, so the SPA served by the app itself gets 401s; `apps/people-analytics-dash` adds a sign-in page that stores user, team and roles for the session and sends them as the `X-Insights-*` headers | Demo-only today; lift it into `templates/web/frontend` when a second team wants a browser demo without the dev server. In production the SSO proxy sets the headers and neither stub exists (ADR-0004) |
| Once an app with a `frontend/` is committed, `pre-commit run --all-files` needs `npm ci` in that app first: the eslint and prettier hooks fail with "run npm ci" when `node_modules` is missing | By design — pre-commit is a convenience, CI is the gate (ADR-0003) — but it now applies to every fresh checkout; ONBOARDING says so, and a hook that skips when `node_modules` is absent is the alternative if it bites |

## Tools

The data-connection registry is the natural seam to expose connections as tools later; nothing in
this repo does so.
