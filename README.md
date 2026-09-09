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

That starts the demo web app on `http://localhost:8080` and the compliance API on `:8000`; the
walkthrough below drives both and the job. Optional backends:

```sh
docker compose --profile postgres -f docker-compose.yml -f compose/postgres.yml up --build
docker compose --profile cache up -d redis
```

The first runs the warehouse and each app's owned database on Postgres instead of the SQLite
fixture; the second adds a shared Redis for apps that set `INSIGHTS_CACHE_URL`.

SSO, the warehouse, and the HR API are stubs. Identity comes from `X-Insights-*` request headers.
By default the warehouse is a SQLite file seeded from
`sdk/src/insights_platform/data/_fixtures/warehouse.sql`; the `postgres` profile mounts the same
file into a Postgres container, so the two fixtures share one source.
The HR API is an in-process fake behind any `*.fixture` host. `.env.example` lists every variable the
fixtures expect; `docker-compose.yml` sets the same values.

## Walkthrough

Fifteen minutes, in the order the brief asks its questions. Every step is something the platform
does for an app that the app did not write.

1. **A team's day one — reuse mechanism ([ADR-0001](docs/adr/0001-thin-sdk-monorepo.md),
   [ADR-0002](docs/adr/0002-generate-dont-clone.md)).** `apps/people-analytics-dash` came out of
   `uv run insights new people-analytics-dash --kind web --team people-analytics` and was changed
   only in its frontend. Its `platform.toml` is the whole contract with the platform: name, team,
   kind, `scaffold_version`, `connections`, `[database]`. Its `pyproject.toml` pins the SDK release
   range. Generate another app and run its tests; nothing else is required.

2. **Sign in — the SSO stub ([ADR-0004](docs/adr/0004-tenant-isolation.md)).** Open
   `http://localhost:8080`. The sign-in page is the stub for the browser: it stores user, team and
   roles for the session and sends them as the `X-Insights-*` headers the corporate SSO proxy will
   set in production. When the real IdP arrives, only `sso.principal_from_headers` changes.

3. **Authorization at the route — enforcement ([ADR-0003](docs/adr/0003-enforcement-placement.md)).**
   Sign in as `dev` / `people-analytics`: the headcount table loads from `GET /api/records`, a route
   marked `@require_team("people-analytics")`. Sign out and sign in as team `finance`: the page shows
   the 403. The compliance app answers the same way:

   ```sh
   curl -i localhost:8000/comp                                                                  # 401
   curl -i -H 'X-Insights-User: sam'  -H 'X-Insights-Team: finance'          localhost:8000/comp  # 403
   curl    -H 'X-Insights-User: dana' -H 'X-Insights-Team: people-analytics' localhost:8000/comp  # 200
   ```

   A route with no marker does not boot: `create_app()` refuses at startup, and the generated tests
   hit that check before a deploy does.

4. **Data access the app never constructs — isolation ([ADR-0004](docs/adr/0004-tenant-isolation.md),
   [ADR-0005](docs/adr/0005-operator-access.md)).** Both apps read the `warehouse` connection they
   declared. `get_engine()` resolved the credential by name from the app's own environment, set the
   timeout, and attached the audit hook and instrumentation. Add `httpx.Client(...)` or
   `create_engine(...)` to an app and `uv run insights check` refuses it, citing the ADR it enforces.

5. **What the platform team can see — operator access ([ADR-0005](docs/adr/0005-operator-access.md),
   [ADR-0006](docs/adr/0006-observability-otel.md)).**

   ```sh
   docker compose logs people-analytics-dash | grep -E 'authz.denied|statement_sha256|db.statement'
   ```

   The denial is an `authz.denied` audit record with the caller's team and the route. The query is a
   `data.query` record carrying a SHA-256 of the statement, and the trace span's `db.statement` is
   the same hash: the platform team sees all the telemetry and none of the compensation data. The
   structured logger refuses a record as a field, so an app cannot log a row by accident.

6. **The batch job — the other consumption model.** `docker compose run --rm finance-nightly-rollup`
   runs an `async def main()` under `run_job()`: exit code 0, `rollup.completed rows=2`,
   `job.completed status=ok`, and the same `data.query` audit record for its one query.

7. **The upgrade story ([ADR-0001](docs/adr/0001-thin-sdk-monorepo.md)).** Change anything under
   `sdk/` on a branch and open a pull request: CI runs lint, types, `insights check` and the tests of
   every app before a release is cut. Each app pins the release range it runs against and moves
   within current-minus-two; `sdk-pin-declared` fails the build when a pin excludes the current
   release.

8. **Deliberate omissions.** [NEXT.md](NEXT.md) lists what is stubbed — SSO, secrets, Kubernetes, a
   trace backend, real break-glass — each with the trigger that would justify building it, and the
   facts this build surfaced for the ADRs.

## The CLI

`insights` ships with the SDK and is the only tool a team needs beyond `uv`. Every command below was
run against this repository today.

```sh
uv run insights new <name> --kind web|job [--team TEAM] [--dest DIR] [--no-frontend]
uv run insights check [APP_DIR ...]
uv run --env-file .env insights db upgrade|downgrade|current|revision [--app APP_DIR]
```

**`insights new`** ([ADR-0002](docs/adr/0002-generate-dont-clone.md)) copies the template out of the
SDK package and substitutes the name, package, team, `scaffold_version` and the SDK release pin.
`--kind web` gives the layered backend under `src/<pkg>/features/`, a `migrations/` directory and a
Vite + React `frontend/`; `--no-frontend` gives the API-only variant with a single-stage Dockerfile;
`--kind job` gives a flat `async def main()`. `--team` defaults to the name, `--dest` to `apps/`. The
name must be kebab-case and the directory must not exist. Then:

```sh
uv sync                                          # the app joins the workspace
uv run pytest apps/<name>                        # passes as generated
uv run insights check apps/<name>                # passes every rule as generated
npm ci --prefix apps/<name>/frontend && npm run dev --prefix apps/<name>/frontend   # web apps
```

**`insights check`** ([ADR-0003](docs/adr/0003-enforcement-placement.md)) runs the nine rules
against every app under `apps/`, or only the directories given, and prints one line per violation:

```
violates ADR-0005: apps must not construct connection clients (httpx.Client); insights_platform.data.get_connection() attaches the credentials, timeouts, and audit hook every data access must carry (apps/x/src/x/main.py:6)
```

Exit code 1 on any violation, `N app(s) checked, no violations` otherwise. The pre-commit hook and
the CI matrix run this same code, so a rule reaches every app the way any SDK change does.

**`insights db`** ([ADR-0007](docs/adr/0007-persistence.md)) wraps Alembic for the app's owned
database, so no app carries an `alembic.ini` or imports Alembic: `upgrade [REVISION]` (default
`head`), `downgrade REVISION` (`-1`, `base`), `current`, and `revision -m TEXT [--autogenerate]`,
which diffs the app's models against the database and writes a file under `migrations/versions/`.
`--app` defaults to the app whose `platform.toml` is found upward from the current directory. It
reads `INSIGHTS_DB_URL`, so run it with `--env-file .env`; on the SQLite fixture the schema is also
created from the models at startup, on Postgres this command is the only path.

## Where things are

```
.
├── sdk/src/insights_platform/   the SDK
│   ├── auth/                    SSO stub, authorization markers, enforcement, boot-time route check
│   ├── data/                    connection registry, get_connection(), fixtures
│   ├── db/                      the app's owned database: get_session(), Base; migrations via insights db
│   ├── cache/                   get_cache(): memory or Redis behind one instrumented seam
│   ├── observability/           OpenTelemetry behind a structured logger; console or OTLP export
│   ├── audit.py                 audit stream for denials and data access
│   ├── config.py                platform.toml -> AppConfig
│   ├── web.py                   create_app()
│   ├── job.py                   run_job()
│   ├── frontend.py              mount_frontend(): a web app's built SPA at /
│   ├── check/                   the nine enforcement rules
│   ├── cli/                     insights new (--no-frontend), insights check, insights db
│   ├── templates/               what insights new copies, frontend/ included
│   └── testing/                 pytest plugin for app tests
├── apps/
│   ├── people-analytics-comp/   example web app, API only (kind = web)
│   ├── people-analytics-dash/   demo web app: React frontend at /, SSO-stub sign-in (kind = web)
│   └── finance-nightly-rollup/  example scheduled job (kind = job)
├── docs/adr/                    architecture decision records
├── .github/                     CI, reusable app-check workflow, CODEOWNERS
├── docker-compose.yml           local deployment; postgres and cache profiles
├── compose/                     the postgres override and its init script
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
| Why apps get an owned database   | [ADR-0007 Persistence](docs/adr/0007-persistence.md) (draft)     |
| Why the page ships with its app  | [ADR-0009 Frontend delivery](docs/adr/0009-frontend-delivery.md) (draft) |
| Why the data seam is async only  | [ADR-0010 Async I/O](docs/adr/0010-async-io.md) (draft)          |
| Day one for a new team           | [ONBOARDING.md](ONBOARDING.md)                                     |
| Every `insights` command         | [The CLI](#the-cli)                                                |
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
- `db.get_session()` and `cache.get_cache()` are built the same way: a URL by name from the
  environment (`INSIGHTS_DB_URL`, `INSIGHTS_CACHE_URL`), mandatory timeouts, an audit hook that
  records table names and row counts or key hashes but never values, and OpenTelemetry. Schema
  changes are Alembic migrations run through `insights db`; on the SQLite fixture the schema comes
  from the models ([ADR-0007](docs/adr/0007-persistence.md),
  [ADR-0004](docs/adr/0004-tenant-isolation.md)).
- Traces are scrubbed before export, whether to the console or over OTLP: `db.statement` becomes
  the same SHA-256 the audit stream records and URLs lose their query strings, so a trace backend
  sees no literal either ([ADR-0005](docs/adr/0005-operator-access.md)).
- `insights check` runs nine rules, each citing the ADR it enforces: `no-raw-drivers`,
  `no-client-construction`, `use-create-app`, `no-private-imports`, `apps-independent`,
  `manifest-valid`, `scaffold-supported`, `sdk-pin-declared`, `no-raw-alembic`. The rules live
  inside the SDK and reach
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

The SDK, CLI, rules, frontend scaffold, the two example apps and the demo web app, CI matrix, and
compose deployment are complete and tested. `BACKLOG.md` is the post-submission plan; wave 1 (trace scrubbing, async I/O,
the frontend scaffold) and wave 2's database and cache have landed; the slice scaffold and its
layering rules are on branch `wt/slices` pending their owned-database phase. ADRs 0001–0006, 0007,
0009 and 0010 are drafts — each opens with a `DRAFT` marker — pending the author's rewrite.
