# Next

What is deliberately not built, what remains before the platform meets every requirement in the
brief, and the trigger that would justify each piece. Ordered by the brief's questions. `BACKLOG.md`
holds the detailed plan and status; this file is the short answer to "what would you do next, and
why".

## What remains, by requirement

| Requirement | Have today | Next, and its trigger |
|-------------|------------|-----------------------|
| **Reuse mechanism and upgrade story** (ADR-0001, ADR-0002) | Thin SDK released and pinned; `sdk-pin-declared`; the CI matrix runs every app against the SDK at `HEAD` before a release; `insights new` records `scaffold_version` | A release process — cutting and approving releases, a changelog, deprecation-shim tooling — at the first SDK change that cannot land in one PR with every dependent. `insights upgrade` at ~12 apps, when hand-migrating between scaffold versions is the biggest time sink |
| **Reuse beyond a Python library** (ADR-0001) | The SDK is the only delivery mechanism | Sidecar for the auth, data-access and telemetry seams: a runtime that co-schedules containers — same trigger as real Kubernetes. Then any of: a tenant that is not Python, a security fix that must cross the fleet without 25 team PRs, or enforcement that has to survive an uncooperative app |
| **Enforcement** (ADR-0003) | Nine static rules with ADR-cited messages in pre-commit, CLI and CI; the boot-time route check; credentials, timeouts, audit and instrumentation attached at construction | The layering rules and the owned-database `records` slice (E3, verified on `wt/slices`), merged when the slice is complete. Data classification enforced at construction (E4) before the second sensitive tenant onboards. A static mirror of the route check only when someone wants it in pre-commit; the boot check is sufficient until then |
| **Isolation** (ADR-0004) | Per-app credentials by name from the app's own environment; an owned database with its own role per app; cache keys namespaced `<app>:` | `revoke connect` on other databases in the Postgres init script (the role can still connect, though not read); per-app Redis ACL users when a shared Redis holds more than one team's data; TLS required on non-local connections (E4). Service mesh: never at 5–25 tenants on one shared runtime. Multi-region: a tenant with a data-residency requirement |
| **Operator access** (ADR-0005, ADR-0006) | The platform team sees telemetry only: audit records carry hashes and counts, traces are scrubbed before export, the logger refuses records as fields | Real break-glass (E7): a signed, time-boxed grant, every access audited, a tenant-readable trail — before the first incident that needs tenant data. A sensitive-field denylist with `Redacted(...)` and `SecretStr` credentials (E4). Exception text in spans is still unscrubbed; fix when Postgres error messages become realistic. A retention policy for the audit stream |
| **Observability** (ADR-0006) | OpenTelemetry logs, metrics and traces; console by default, OTLP by environment; six required log fields | Grafana / Tempo / Loki compose profile the first time someone needs to look at a trace rather than grep a log — zero SDK change, the seam is already OTLP. Swap the deprecated `LoggingHandler` for `opentelemetry-instrumentation-logging` |
| **Authentication** (stubbed) | Identity from `X-Insights-*` headers; the Vite proxy and the demo app's sign-in page stand in for the SSO proxy in the browser | A real IdP behind `sso.principal_from_headers`, the one function that changes. Decide whether team is mandatory (a missing `X-Insights-Team` is `""` today, so `require_team` simply denies). Retire the browser stubs when the SSO proxy exists, or lift the sign-in page into the template if a second team needs the demo path |
| **Deployment** (compose) | Both apps and the job under compose; Postgres and Redis profiles; multi-stage image for web apps with a frontend | Real Kubernetes manifests at the first environment that is not a single compose host. A secrets manager at the first real credential. `insights deploy` when compose stops matching how production deploys. Circuit breaker and retry policy at the first partial outage of a shared source — `get_connection()` owns construction, so it lands in one place |
| **Web apps and frontends** (ADR-0009) | Vite + React scaffold served by the app under `/`, API under `/api` | `index.html` fallback for client-side routes when the first app needs them; label static requests `static` in the request counter; path-filter the frontend CI job to `frontend/**` when CI time bites |
| **Scale to ~25 teams** | Scaffold and CODEOWNERS per team | Self-service portal at ~15 tenants, when scaffold support exceeds an engineer-week per month. `insights check --format json`, `insights new --force`, `insights new` running `uv sync` (E8) when someone asks |
| **Considered and rejected** | — | `import-linter`: its contract config would live outside the SDK package, so rules would not be versioned with the SDK |

## What the build taught the ADRs

Facts the author needs when rewriting the drafts; each changes or sharpens an argument.

- `uv` silently drops a declared version constraint when `[tool.uv.sources]` maps the dependency to a
  workspace member, so the SDK pin is a contract the workspace cannot enforce and `sdk-pin-declared`
  has to (ADR-0001, ADR-0003).
- The data seam is one async API — `AsyncEngine`, `httpx.AsyncClient`, `run_job()` takes a coroutine
  function — and no sync variant exists, so the compatibility surface stays enumerable (ADR-0001,
  ADR-0010).
- Traces carried full SQL text until E0. `ReadableSpan` attributes are frozen before any processor
  runs, so scrubbing rebuilds the span inside a wrapper: it is structural, not a matter of processor
  order. ADR-0005 must say traces are telemetry too and how they are scrubbed.
- Static rules see literal paths and prefixes and routers built in the same module; whether an
  import reaches a submodule or a re-export is undecidable statically. They catch accidental and lazy
  bypass, not adversarial bypass, and say so (ADR-0003).
- The frontend mount is not an `APIRoute`: `check_routes` ignores it and no marker applies, so the
  page shell is public and only `/api` is protected (ADR-0009, ADR-0005).
- Token substitution has no conditionals, so `--no-frontend` works by skipping `frontend/**` and
  swapping `<file>.no-frontend.tmpl` variants — ADR-0002's "more than a name" trigger has fired in a
  small way.
- Owned databases have two schema paths on purpose: models on the SQLite fixture, migrations on
  Postgres, so a unit test cannot prove a migration and the `integration` marker exists (ADR-0007).
- Cache isolation is a key prefix evaluated per call; two apps on one Redis cannot read each other's
  keys, but per-app ACL users are the stronger step (ADR-0004).
- The browser needs an SSO stub as much as `curl` does; production has neither because the SSO proxy
  sets the headers (ADR-0004).
- `/readyz` now performs I/O and writes an audit record per probe; compose polls every ten seconds
  (ADR-0005, ADR-0006).
- Required log fields are reserved and a caller passing one gets `ValueError`; every `get_logger()`
  name is namespaced under `insights.`; `observability.configure()` is once per process, so one app
  per process (ADR-0006).
- Pre-commit is a convenience and CI is the gate: once an app with a frontend is committed,
  `pre-commit run --all-files` needs `npm ci` in that app first (ADR-0003).

## Tools

The data-connection registry is the natural seam to expose connections as tools later; nothing in
this repo does so.
