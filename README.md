# Insights Hub

A paved road for internal insight apps: a thin Python SDK, a scaffold CLI, a set of enforcement
rules, and a deployment template. Apps stay ordinary FastAPI apps or plain scripts; the platform owns
the cross-cutting seams — authentication, authorization, data access, observability, and the path to
a container — so teams do not hand-roll them.

Context: internal only, about five consuming teams today and plausibly twenty-five in two years, run
by a platform team of two to three engineers who also maintain everything in this repository.

## Run it

```sh
uv sync
uv run pytest && uv run insights check
```

`uv run pytest` runs the SDK's tests. `uv run insights check` runs the platform rules against every
app under `apps/`. To run one app's tests: `uv run pytest apps/people-analytics-comp`.

Windows: the test fixtures under `sdk/tests/fixtures` reach 114 characters. If you clone deeper than
about 140 characters, run `git config core.longpaths true` first or the checkout stops partway with
"Filename too long" and `uv run pytest` finds no tests.

```sh
docker compose up
```

Then, in another shell:

```sh
curl localhost:8000/healthz
curl -i -H 'X-Insights-User: sam'  -H 'X-Insights-Team: finance'          localhost:8000/comp  # 403
curl    -H 'X-Insights-User: dana' -H 'X-Insights-Team: people-analytics' localhost:8000/comp  # 200
docker compose run --rm finance-nightly-rollup
```

SSO, the warehouse, and the HR API are stubs. Identity comes from `X-Insights-*` request headers.
The warehouse is a SQLite file seeded from `sdk/src/insights_platform/data/_fixtures/warehouse.sql`.
The HR API is an in-process fake behind any `*.fixture` host. `.env.example` lists every variable the
fixtures expect; `docker-compose.yml` sets the same values.

## Where things are

```
.
├── sdk/src/insights_platform/   the SDK
│   ├── auth/                    SSO stub, authorization markers, enforcement, boot-time route check
│   ├── data/                    connection registry, get_connection(), fixtures
│   ├── observability/           OpenTelemetry behind a structured logger; console or OTLP export
│   ├── audit.py                 audit stream for denials and data access
│   ├── config.py                platform.toml -> AppConfig
│   ├── web.py                   create_app()
│   ├── job.py                   run_job()
│   ├── frontend.py              mount_frontend(): a web app's built SPA at /
│   ├── check/                   the eight enforcement rules
│   ├── cli/                     insights new (--no-frontend), insights check
│   ├── templates/               what insights new copies, frontend/ included
│   └── testing/                 pytest plugin for app tests
├── apps/
│   ├── people-analytics-comp/   example web app (kind = web)
│   └── finance-nightly-rollup/  example scheduled job (kind = job)
├── docs/adr/                    architecture decision records
├── .github/                     CI, reusable app-check workflow, CODEOWNERS
├── docker-compose.yml           local deployment
├── ONBOARDING.md                day one for a new team
└── NEXT.md                      deliberate omissions and findings
```

| Looking for                      | Go to                                                              |
|----------------------------------|--------------------------------------------------------------------|
| Why the platform is a library    | [ADR-0001 Thin SDK, released and pinned](docs/adr/0001-thin-sdk-monorepo.md) |
| Why apps are generated           | [ADR-0002 Generate, don't clone](docs/adr/0002-generate-dont-clone.md) |
| Where each rule is enforced      | [ADR-0003 Enforcement placement](docs/adr/0003-enforcement-placement.md) |
| What tenants share               | [ADR-0004 Tenant isolation](docs/adr/0004-tenant-isolation.md)     |
| What the platform team can see   | [ADR-0005 Operator access](docs/adr/0005-operator-access.md)       |
| How telemetry leaves an app      | [ADR-0006 Observability: OpenTelemetry as the wire contract](docs/adr/0006-observability-otel.md) |
| Why the page ships with its app  | [ADR-0009 Frontend delivery](docs/adr/0009-frontend-delivery.md) (draft) |
| Why the data seam is async only  | [ADR-0010 Async I/O](docs/adr/0010-async-io.md) (draft)          |
| Day one for a new team           | [ONBOARDING.md](ONBOARDING.md)                                     |
| What was left out, and why       | [NEXT.md](NEXT.md)                                                 |
| The original brief               | [docs/BRIEF.md](docs/BRIEF.md)                                     |

## How the platform reaches an app

- `create_app()` and `run_job()` own the boot sequence: load `platform.toml`, configure telemetry,
  install auth before any route exists, add `/healthz` and `/readyz`, and at startup refuse to run if
  any route lacks an authorization marker or any declared connection cannot be built
  ([ADR-0003](docs/adr/0003-enforcement-placement.md)). A web app's built `frontend/dist` is
  mounted at `/` only after that check, so `/api/*` and the health routes keep precedence
  ([ADR-0009](docs/adr/0009-frontend-delivery.md)).
- `get_connection()` owns client construction. Credentials are resolved from the environment by
  connection name, timeouts are mandatory, every query and request is audited with the principal, and
  OpenTelemetry instrumentation is attached. An app cannot skip any of it because it never constructs
  a client ([ADR-0005](docs/adr/0005-operator-access.md)). The objects are async — a SQLAlchemy
  `AsyncEngine`, an `httpx.AsyncClient` — and `run_job()` runs an `async def main()`; there is no
  sync variant ([ADR-0010](docs/adr/0010-async-io.md)).
- Traces are scrubbed before export, whether to the console or over OTLP: `db.statement` becomes
  the same SHA-256 the audit stream records and URLs lose their query strings, so a trace backend
  sees no literal either ([ADR-0005](docs/adr/0005-operator-access.md)).
- `insights check` runs eight rules, each citing the ADR it enforces: `no-raw-drivers`,
  `no-client-construction`, `use-create-app`, `no-private-imports`, `apps-independent`,
  `manifest-valid`, `scaffold-supported`, `sdk-pin-declared`. The rules live inside the SDK and reach
  apps through three
  entry points: the pre-commit hook, the CLI, and the CI matrix
  ([ADR-0003](docs/adr/0003-enforcement-placement.md)).
- `.github/CODEOWNERS` gives each team its own `apps/<name>/` and keeps `platform.toml`, `sdk/`,
  `.github/`, and `docs/adr/` with the platform team ([ADR-0004](docs/adr/0004-tenant-isolation.md)).

## The upgrade story

The SDK ships as approved releases and each app pins the range it runs against, so a team chooses
when to move within a window of the current release minus two. The monorepo is what makes that
safe to publish: `ci.yml` sees that `sdk/**` changed and runs `app-check.yml` for every app —
lint, types, `insights check`, tests — against the SDK at `HEAD` before a release is cut, while an
app-only change runs only that app. A breaking change ships behind a deprecation shim in one
release and loses it two releases later.

`uv` ignores a declared version constraint when `[tool.uv.sources]` maps the dependency to a
workspace member, so the pin is not self-enforcing in development; the `sdk-pin-declared` rule is
what checks it. `app-check.yml` is a `workflow_call` workflow, so a team that later leaves the
monorepo consumes the same gate from its own repository
([ADR-0001](docs/adr/0001-thin-sdk-monorepo.md)).

## Deliberate omissions

[NEXT.md](NEXT.md) is the authoritative list, each with the trigger that would justify building it.
The five that matter most:

- Real Kubernetes manifests — the first environment that is not a single compose host.
- Secrets manager integration — the first real credential; today every value is a fixture.
- Grafana / Tempo / Loki compose profile — the first time someone needs to look at a trace rather
  than grep a log. The seam is already OTLP, so this is zero SDK change.
- `insights upgrade` — around twelve apps, when hand-migrating between scaffold versions is the
  team's biggest time sink.
- Self-service portal — around fifteen tenants, when scaffold support exceeds an engineer-week per
  month.

## Status

The SDK, CLI, rules, frontend scaffold, both example apps, CI matrix, and compose deployment are
complete and tested. `BACKLOG.md` is the post-submission plan; its wave 1 — trace scrubbing, async
I/O, the frontend scaffold — has landed. All eight ADRs (0001–0006, 0009, 0010) are drafts — each
opens with a `DRAFT` marker — pending the author's rewrite.
