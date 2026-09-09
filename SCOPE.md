# Insights Hub — Scope (12-hour window)

Working doc for the day. Anything not on this page goes in `NEXT.md`, not in the repo.

---

## What this is

A **paved road** for internal insight apps: a thin Python SDK + a scaffold CLI + enforcement rules +
a deployment template. Not a framework. Apps stay FastAPI apps or plain scripts; the platform owns
the cross-cutting seams (auth, permissions, data access, observability, deploy) so teams don't
hand-roll them.

Graded on: ADRs first, scoping second, code as evidence. Not completeness.

**Naming.** Package `insights_platform`, distribution `insights-platform`, CLI `insights`. Never
`platform` — it shadows the stdlib module. The app manifest is `platform.toml` (a filename, not an
identifier; no collision).

---

## Locked decisions (each becomes an ADR)

| # | Decision | One-line argument | Trade-off named |
|---|----------|-------------------|-----------------|
| 1 | **Thin SDK, released and pinned, developed in a monorepo.** Not a service, not a framework. The SDK ships as approved releases; each app pins a range and moves within a window of current-minus-two. | 2–3 engineers can't operate a control plane. Colocation and versioning answer different questions and are independent: the monorepo runs every dependent's tests before a release is cut (the proof a published package alone can't give), the pin gives a tenant its own timing and gives the platform a canary. Compat surface is four enumerable seams: auth interface, data-connection interface, log schema, config contract. | A release process to run, and up to three SDK versions live at once. Deprecation shims invert from exception to routine. `uv` drops a declared constraint for a workspace source, so `sdk-pin-declared` has to enforce the pin. Exit ramp for a tenant the workspace can't hold: the `workflow_call` check workflow is consumable from any repo. |
| 2 | **Generate, don't clone.** `insights new` copies a template from *inside the SDK package* and substitutes `__NAME__`. Records `scaffold_version` in `platform.toml`. | Cloned templates freeze at clone time and drift invisibly. `scaffold_version` (what generated the app) is the one fact a future `insights upgrade` needs; the SDK release it runs against is a separate fact, the pinned range in its `pyproject.toml`. No template engine — copy and substitute is enough. | CLI is one more thing to maintain. |
| 3 | **Enforcement placement.** Structural rules → static checks, one rule set in `insights_platform.check`, versioned with the SDK, three entry points (pre-commit, `insights check`, CI). AuthZ + data access → runtime, non-bypassable, guaranteed at *construction* (`create_app()`, `get_connection()`). Review process → CODEOWNERS. Convention → only where wrong is recoverable. | Compensation data cannot rest on convention. Static checks catch accidental and lazy bypass; they do not catch adversarial bypass and are not claimed to — that is handled by the environment's stated facts (ADR 4) plus review. Every rule message cites the ADR it enforces. Rules living in the SDK means a new rule reaches apps the same way any SDK change does. | Runtime enforcement adds SDK coupling. Pre-commit hooks are convenience and bypassable; CI + branch protection is the authoritative gate. |
| 4 | **Isolation.** Shared: runtime, telemetry pipeline, deploy path, SSO. Per-tenant: data-connection credentials (resolved by name at startup from the app's own env), log/metric/trace namespaces (OTel resource attributes `app`, `team`), authZ policy. | Internal employees + org recourse → no SaaS-grade blast-radius isolation. People Analytics tenant → hard runtime enforcement on data access *is* needed. State both facts. | Shared runtime means noisy-neighbor risk (accepted at 5–25 tenants). |
| 5 | **Operator access.** Platform team: all telemetry by default, no tenant data by default. Break-glass: time-boxed grant, logged to an audit stream the tenant can read, stubbed approval. | This is what the compliance-partner review is testing. **Named hole:** logs are telemetry, and apps can put data in logs. The structured logger accepts schema fields only — no free-text dict passthrough — so "platform sees all telemetry" does not silently become "platform sees comp records." Enforced by API shape + review, and said out loud. | Break-glass friction slows incident response. |
| 6 | **Observability.** OpenTelemetry is the wire contract for logs, metrics, traces. Console exporter by default; OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Required log fields: `app`, `team`, `principal`, `request_id`, `trace_id`, `span_id`. | Vendor-neutral seam. A Grafana/Tempo/Loki stack later is a compose profile and zero SDK changes; log↔trace correlation works on day one because the IDs are already in the schema. Alternative (structlog + prometheus_client directly) is lighter but locks the seam to two libraries. | OTel SDK weight in a "thin" SDK; OTel API churn. |

**Deliberate omissions** → README section (a list, not a decision). Each with its trigger:
real K8s, secrets manager, service mesh, self-service portal (~15 tenants, when scaffold support
exceeds an engineer-week/month), multi-region, `insights upgrade` (~12 apps, when hand-migrating is
the biggest time sink), `insights deploy`, LGTM compose profile (first time someone needs to *look*
at a trace rather than grep a log), circuit breaker / retry policy on connections (first partial
outage of a shared source), static mirror of the route-authZ rule (runtime check is sufficient
until someone wants it in pre-commit), import-linter (considered; rejected because contract config
would live outside the SDK package).

---

## Repo layout

```
insights-hub/
├── .github/
│   ├── CODEOWNERS                  # last-match-wins: apps/<x>/ → that team; platform paths → platform team
│   ├── actions/setup/action.yml    # composite: install uv, uv sync --frozen, cache
│   └── workflows/
│       ├── ci.yml                  # paths-filter → sdk job + apps matrix (uses app-check) → aggregate status
│       └── app-check.yml           # workflow_call(app-path): ruff, insights check, pytest for one app
├── .editorconfig
├── .gitattributes                  # * text=auto eol=lf
├── .gitignore
├── .pre-commit-config.yaml         # ruff, ruff-format, detect-secrets, hygiene, local: insights check
├── .secrets.baseline
├── .env.example                    # every env var a declared connection needs; values are fixtures
├── pyproject.toml                  # uv workspace root: members = ["sdk", "apps/*"]; ruff/mypy/pytest config
├── uv.lock
├── docker-compose.yml              # both apps; observability profile is a NEXT stub
├── README.md                       # run in 2–3 commands; map to ADRs / ONBOARDING / NEXT; deliberate omissions
├── ONBOARDING.md
├── NEXT.md
├── docs/
│   ├── BRIEF.md                    # moved here at cleanup
│   └── adr/
│       ├── 0001-thin-sdk-monorepo.md
│       ├── 0002-generate-dont-clone.md
│       ├── 0003-enforcement-placement.md
│       ├── 0004-tenant-isolation.md
│       ├── 0005-operator-access.md
│       └── 0006-observability-otel.md
├── sdk/
│   ├── pyproject.toml              # name = "insights-platform"; [project.scripts] insights = ...
│   ├── src/insights_platform/
│   │   ├── __init__.py
│   │   ├── _internal/              # apps may not import from here (rule: no-private-imports)
│   │   ├── auth/
│   │   │   ├── __init__.py         # Principal, get_principal, require_role, require_team, public
│   │   │   ├── sso.py              # stub: headers → Principal
│   │   │   └── authz.py            # deny-by-default; route marker check at create_app() startup
│   │   ├── data/
│   │   │   ├── __init__.py         # get_connection(name) → configured Engine | httpx.Client
│   │   │   ├── registry.py         # name → spec → constructed client (creds, timeouts, audit hooks, OTel)
│   │   │   └── _fixtures/          # fake warehouse (sqlite), fake REST API (httpx.MockTransport)
│   │   ├── observability/
│   │   │   ├── __init__.py         # get_logger, get_meter, get_tracer
│   │   │   └── _otel.py            # providers; console vs OTLP by env; resource attrs app/team
│   │   ├── audit.py                # audit sink: authZ denials, data access, break-glass
│   │   ├── config.py               # load platform.toml → AppConfig; creds from env; fail fast
│   │   ├── web.py                  # create_app(): auth middleware, /healthz, /readyz, route-authZ check
│   │   ├── job.py                  # run_job(): context, job.completed{status} metric, exit code
│   │   ├── testing/
│   │   │   └── __init__.py         # pytest plugin: principal fixture, fake connections, test client
│   │   ├── check/
│   │   │   ├── __init__.py         # rule runner; globs apps/* when no path given
│   │   │   └── rules/              # one module per rule; each cites its ADR
│   │   ├── cli/
│   │   │   ├── __init__.py         # typer app
│   │   │   ├── new.py
│   │   │   └── check.py
│   │   └── templates/
│   │       ├── web/                # __NAME__ substitution
│   │       └── job/
│   └── tests/
│       ├── test_auth.py
│       ├── test_data.py
│       ├── test_observability.py
│       ├── test_config.py
│       ├── test_web.py
│       ├── test_job.py
│       ├── test_cli.py
│       ├── test_check.py           # runs every rule against fixtures/broken_apps — each must fail
│       └── fixtures/broken_apps/   # one minimal app per rule, violating exactly that rule
└── apps/
    ├── people-analytics-comp/      # web — the comp endpoint is the authZ-protected one
    │   ├── pyproject.toml
    │   ├── platform.toml
    │   ├── Dockerfile
    │   ├── README.md
    │   ├── src/people_analytics_comp/
    │   │   ├── __init__.py
    │   │   └── main.py             # app = create_app(); two routes
    │   └── tests/test_main.py      # uses insights_platform.testing fixtures
    └── finance-nightly-rollup/     # job
        ├── pyproject.toml
        ├── platform.toml
        ├── Dockerfile
        ├── README.md
        ├── src/finance_nightly_rollup/
        │   ├── __init__.py
        │   └── main.py             # run_job(...)
        └── tests/test_main.py
```

**`platform.toml`**

```toml
[app]
name = "people-analytics-comp"
team = "people-analytics"
kind = "web"                      # web | job
scaffold_version = "0.1.0"
connections = ["warehouse"]       # must exist in the registry; creds resolved from env at startup
```

**`insights check` rules** (each message: `violates ADR-000N: <intent>`)

| Rule | Mechanism | ADR |
|------|-----------|-----|
| `no-raw-drivers` | apps may not import `psycopg`, `asyncpg`, `requests`, `urllib.request` | 3, 5 |
| `no-client-construction` | apps may not call `create_engine`, `httpx.Client`, `httpx.AsyncClient`, `httpx.get/post/...`; importing `sqlalchemy`/`httpx` for types and exceptions is fine | 5 |
| `use-create-app` | apps may not call `FastAPI(` directly | 3 |
| `no-private-imports` | apps may not import `insights_platform._internal` | 1 |
| `apps-independent` | `apps/*` may not import each other; SDK never imports apps | 4 |
| `manifest-valid` | `platform.toml` present, required keys, every declared connection exists in the registry | 2, 4 |
| `scaffold-supported` | `scaffold_version` within N-2 of current | 1, 2 |
| `sdk-pin-declared` | app pins `insights-platform` to a range admitting the current release | 1 |

Route-level authZ (every route carries `require_*` or `@public`) is a **runtime** check at
`create_app()` startup — the app refuses to boot otherwise. That is the non-bypassable version.

---

## Deliverables

### SDK (`sdk/`)
- [ ] SSO stub — headers → `Principal` with team + roles
- [ ] AuthZ — `require_role`, `require_team`, `public`; denies by default; startup check that every route is marked
- [ ] Data-connection registry — `get_connection("warehouse")` returns a real, configured `Engine` / `httpx.Client`. SDK owns construction: name → creds from env, mandatory timeouts, audit hooks (`before_cursor_execute` / httpx `event_hooks`), OTel instrumentation. Undeclared connection → startup error.
- [ ] Observability — OTel logs/metrics/traces; console by default, OTLP by env; required log fields; schema-only logger (no free-text dict)
- [ ] Health — `create_app()` installs `/healthz`, `/readyz`; `run_job` emits `job.completed{status}` and a defined exit code
- [ ] Config — `platform.toml` → `AppConfig`; creds from env; `.env.example` at root; fail fast on missing
- [ ] Audit sink — authZ denials, data access, break-glass
- [ ] `insights_platform.testing` — `principal` fixture, fake connections, test client
- [ ] `insights_platform.check` — the seven rules above, ADR-cited messages, broken-app fixtures
- [ ] Templates for `web` and `job` (inside package, `__NAME__`)

### CLI — two commands
- [ ] `insights new <name> --kind web|job` → copy template, substitute, write `platform.toml`
- [ ] `insights check [path]` → run rules; no path = all `apps/*`; same code CI runs

### Two thin apps (`apps/`)
- [ ] `people-analytics-comp` — FastAPI via `create_app()`, two endpoints, `/comp` is `require_team("people-analytics")`, reads warehouse fixture
- [ ] `finance-nightly-rollup` — `run_job`, reads a connection, logs a result, exits

### Repo hygiene (production-grade baseline)
- [ ] `uv` workspace, single lockfile; `ruff` (lint + format), `mypy --strict` on SDK, `pytest`
- [ ] `.pre-commit-config.yaml` with header stating hooks are convenience; CI is the gate
- [ ] `.editorconfig`, `.gitattributes` (LF), `.secrets.baseline`, `CODEOWNERS`
- [ ] `docker-compose.yml` for both apps

### CI (`.github/`)
- [ ] `app-check.yml` — `workflow_call(app-path)`: ruff, `insights check`, pytest
- [ ] `ci.yml` — paths-filter: SDK change → full `apps/*` matrix; app change → that app; SDK job (ruff, mypy, pytest); one aggregate `ci-ok` job; `permissions: contents: read`
- [ ] `actions/setup` composite

### Docs
- [ ] 6 ADRs (context / decision / alternatives / consequences — short)
- [ ] `ONBOARDING.md` — team #6, literal day one: create app, get auth + data access, deploy, know it's healthy
- [ ] Root `README.md` — run in 2–3 commands; map to ADRs / onboarding / NEXT; deliberate omissions section
- [ ] `NEXT.md` — running all day, cleaned up at the end

---

## Clock

| Hours | Block | Exit criterion |
|-------|-------|----------------|
| 0–1 | Decisions confirmed, repo skeleton (workspace, pyproject, pre-commit, editorconfig, gitattributes, CODEOWNERS), ADR stubs, `NEXT.md` | 6 ADR files exist; `uv sync` passes; `pre-commit install` works |
| 1–4 | SDK: auth, authZ, connections, OTel, config, audit, testing fixtures | Import works; auth, connection, logging each have one passing test |
| 4–5.5 | Two apps + `insights new` (copy + substitute) | `insights new` generates a runnable app; both example apps run |
| 5.5–6.5 | `insights check` rules + `app-check.yml` + `ci.yml` | `insights check` passes on both apps and fails on every broken fixture; CI green |
| 6.5–8.5 | **ADRs written properly** | Each names the tension and the trade-off. Do not let code steal this block. |
| 8.5–10 | ONBOARDING, README, NEXT cleanup; move BRIEF to `docs/`; delete this file | A stranger could follow README from clone to running app |
| 10–11 | Fresh clone, follow own README, fix breaks, cut unfinished → NEXT | Clean-clone run passes |
| 11–12 | Buffer | If this is spent on features, scoping failed |

---

## Rules for the day

1. **Does this change an ADR's argument?** If no → `NEXT.md`.
2. AI writes boilerplate and tests. **I write every ADR sentence.** The 75-minute session is live defense against my own code.
3. No MCP, no LangGraph, no LLM anything. Max: one sentence in `NEXT.md` noting the data-connection abstraction is exposable as tools later.
4. Stubs everywhere infra would be. No cloud, no real SSO, no real warehouse.
5. Hit the wall → stop, write what's next and why. Prioritization is scored; endurance is not.

---

## Likely live-session curveballs (prep the shape of the answer, not the code)

- "A tenant needs isolation you didn't build" → ADR 4's stated facts; which fact changed?
- "Breaking SDK change, 12 dependents" → ADR 1: one PR, CI matrix, CODEOWNERS; shim window only if one PR can't do it
- "Compliance wants proof nobody read comp data" → ADR 5 audit stream via `get_connection` hooks; coverage is 100% *because* of the construction rule; what's evidenced, what isn't yet
- "Your platform team can read all logs — what stops an app logging comp records?" → ADR 5 named hole; schema-only logger
- "A team wants to bypass the SDK for one endpoint" → ADR 3: which layer catches it (`use-create-app` static; route-authZ at boot), and is that the right layer?
- "Where's the Grafana?" → ADR 6: seam is OTLP; compose profile is a NEXT item; zero SDK change
