# Next

What was consciously left out, and what would trigger building it. Running list during the build;
cleaned up at the end.

## Deliberate omissions

| Omission | Trigger to build it |
|----------|---------------------|
| Real Kubernetes manifests | First environment that isn't a single compose host |
| Secrets manager integration | First real credential; today every value is a fixture |
| Service mesh | Never at 5–25 tenants on one shared runtime; revisit if tenants leave it |
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
| The fresh-clone test failed on Windows: fixture paths reach 114 characters, and a clone 151 characters deep crossed `MAX_PATH`, so checkout stopped partway and `uv run pytest` found no tests | Documented in the README; shorten the fixture app names if a second person hits it |

## Tools

The data-connection registry is the natural seam to expose connections as tools later; nothing in
this repo does so.
