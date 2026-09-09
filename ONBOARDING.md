# Onboarding: your first day on Insights Hub

This is for a team joining the platform. It walks through creating an app, getting a request
through auth, reaching a data connection, shipping, and knowing the app is healthy.

## What you get, and what stays yours

The platform gives you authentication, authorization, audited data access, structured logs, metrics,
traces, health endpoints, a container build, and a CI gate. You keep your routes or job logic, your
tests, your `README.md`, and the settings in your `platform.toml`. You never write connection strings,
auth middleware, or logging setup.

## Before you start

```sh
git clone <this repository> && cd enterprise_platform
uv sync
uv run pre-commit install
cp .env.example .env
```

`.env` holds the connection variables the SDK reads at startup (`INSIGHTS_CONN_*`) and the optional
OTLP endpoint. Every value in `.env.example` points at a fixture: a SQLite warehouse under `.local/`
and an in-process HR API. Nothing in it is a real credential.

## Create your app

```sh
uv run insights new reporting-dash --kind web --team reporting
```

The name must be kebab-case (`^[a-z][a-z0-9-]*$`). `--kind` is `web` or `job`. `--team` defaults to
the name. The command prints:

```
Created apps/reporting-dash
Next:
  uv sync
  uv run pytest apps/reporting-dash
  uv run insights check apps/reporting-dash
```

Run `uv sync` so the new app joins the workspace. The generated tree:

```
apps/reporting-dash/
├── Dockerfile                        builds from the repo root; installs only your package
├── platform.toml                     the platform manifest (below)
├── pyproject.toml                    depends on insights-platform through the workspace
├── README.md                         how to run, verify, and build this app
├── src/reporting_dash/__init__.py
├── src/reporting_dash/main.py        create_app() plus two routes, or main() for a job
└── tests/test_main.py                passes as generated
```

`platform.toml` is the contract between your app and the platform:

```toml
[app]
name = "reporting-dash"          # must equal the directory name
team = "reporting"               # your team; sets the tenant on every log line and metric
kind = "web"                     # web or job; create_app() and run_job() refuse the other
scaffold_version = "0.1.0"       # the template version that generated this app
connections = ["warehouse"]      # every connection you will call get_connection() for
```

`scaffold_version` records what generated the app so a future `insights upgrade` knows which
migration to apply; you do not edit it. `connections` must list every connection you use: the SDK
builds each one at startup, so a missing credential fails before the first request, and a name you
did not declare is refused at the call site. The platform team owns this file in `CODEOWNERS`.

## Run it locally

Web app, from the repository root:

```sh
uv run --env-file .env uvicorn reporting_dash.main:app --reload
```

Job:

```sh
uv run --env-file .env python -m reporting_nightly.main
```

Logs are JSON, one object per line, on stdout. A job run prints its own line, the audit line for the
query it made, and a completion line. Trimmed to the fields that matter:

```json
{"body": "rollup.completed", "severity_text": "INFO",
 "attributes": {"rows": 2, "app": "reporting-nightly", "team": "reporting",
                "principal": "job:reporting-nightly", "request_id": "32dccf24…",
                "trace_id": "33779166…", "span_id": "b41bc407…"},
 "timestamp": "2026-09-09T16:22:18.343504Z"}
```

OpenTelemetry adds `code.file.path`, `code.function.name`, and `code.line.number` to each record as
well. The `resource` block on every record carries `service.name`, `insights.app`, and
`insights.team`.

## Auth: getting a request through

SSO is a stub. Identity arrives in three headers:

| Header             | Meaning                                  |
|--------------------|------------------------------------------|
| `X-Insights-User`  | user id; required, or the request is 401 |
| `X-Insights-Team`  | the caller's team                        |
| `X-Insights-Roles` | comma-separated roles                    |

Every route must carry exactly one kind of marker:

```python
from insights_platform.auth import public, require_role, require_team


@app.get("/")
@public  # anyone, no headers needed
def root() -> dict[str, str]: ...


@app.get("/records")
@require_team("reporting")  # caller's team must be one of these
def records() -> list[dict]: ...


@app.get("/admin")
@require_team("reporting")
@require_role("admin", "owner")  # stacked: team must match AND one of the roles must match
def admin() -> dict[str, str]: ...
```

Several values in one marker are any-of. Stacking `require_team` and `require_role` requires both.
`public` cannot be combined with either. A request with no `X-Insights-User` is 401 and writes an
`authn.missing` audit record; a request whose team or roles do not satisfy the markers is 403 and
writes `authz.denied` with the route, the caller's team, and what was required.

An unmarked route does not start the app. `create_app()` checks every route during startup and
raises:

```
insights_platform.auth.UnprotectedRouteError: unprotected routes:
  GET /records: no authorization marker (require_role/require_team/public)
```

Your generated tests use `client_for(app)`, which runs that startup check, so a missing marker fails
your tests before it fails your deploy. When real SSO arrives, only
`insights_platform.auth.sso.principal_from_headers` changes; your routes and markers do not.

## Data: getting to a connection

Three steps:

1. Declare the connection in `platform.toml` — `connections = ["warehouse", "hr-api"]`.
2. Provide its variables, named `INSIGHTS_CONN_<NAME>_<KEY>` with the name upper-cased and `-`
   replaced by `_`:

   | Connection  | Variables                                                     |
   |-------------|---------------------------------------------------------------|
   | `warehouse` | `INSIGHTS_CONN_WAREHOUSE_URL`                                 |
   | `hr-api`    | `INSIGHTS_CONN_HR_API_URL`, `INSIGHTS_CONN_HR_API_TOKEN`      |

3. Call `get_engine("warehouse")` for a SQLAlchemy `Engine` or `get_http_client("hr-api")` for an
   `httpx.Client`. Both are the real library objects; use them as you normally would.

If you call a connection you did not declare, you get
`ConnectionNotDeclaredError: connection 'hr-api' is not declared in platform.toml (declared:
warehouse)`. If a declared connection's variable is unset, startup fails with
`MissingCredentialError: connection 'warehouse' requires environment variable
INSIGHTS_CONN_WAREHOUSE_URL, which is not set`. Both are deliberate: an app never limps into service
with a connection it cannot use.

At construction the SDK resolves the credential, sets a 10-second timeout, attaches OpenTelemetry
instrumentation, and attaches an audit hook. Every SQL statement writes a `data.query` audit record
with the connection name and a SHA-256 of the statement — never the statement text. Every HTTP
request writes `data.request` with the method and host plus path — never the query string. The
principal and request id are on both.

The first rule you will meet: do not call `httpx.Client(...)`, `httpx.get(...)`, or
`sqlalchemy.create_engine(...)` yourself. A client you build has no credential resolution, no
timeout, no audit hook, and no instrumentation, and the compliance claim "every data access is
evidenced" stops being true. `insights check` fails the build if you do.

## Ship it

```sh
uv run insights check apps/reporting-dash
```

A clean run prints `1 app(s) checked, no violations`. A violation looks like this:

```
violates ADR-0005: apps must not construct connection clients (httpx.Client);
insights_platform.data.get_connection() attaches the credentials, timeouts, and audit hook every
data access must carry (apps/reporting-dash/src/reporting_dash/main.py:6)
```

The same check runs as a pre-commit hook whenever files under `apps/` change, and in CI. Open a pull
request; CI runs lint, `mypy --strict`, `insights check`, and your tests for your app only. If the
SDK changed in the same PR, it runs for every app. `CODEOWNERS` makes your team the owner of
`apps/reporting-dash/` except `platform.toml`, which stays with the platform team.

To run in a container, add a service to `docker-compose.yml` shaped like the two existing ones
(build context is the repository root, `dockerfile` is your app's), then `docker compose up`. Web
apps expose port 8000; jobs run once with `docker compose run --rm <service>`. Deployment beyond
compose is not built: `NEXT.md` records `insights deploy` and real Kubernetes manifests as deliberate
omissions, each with the trigger that would justify them.

## Know it is healthy

Web apps get two routes with no auth required. `/healthz` returns 200 whenever the process is up.
`/readyz` confirms every declared connection can be built and returns 200, or 503 with
`{"status": "unavailable", "error": "<ExceptionClass>"}` when one cannot. Compose uses
`/readyz` as the health check.

Jobs return exit code 0 when `main()` completed and 1 when it raised. Either way the run writes
`job.completed` with `status` (`ok` or `failed`), `duration_ms`, and on failure the exception class in
`error`, and increments the `insights.job.runs` counter labelled by status.

Every log line carries six fields: `app`, `team`, `principal`, `request_id`, `trace_id`, and
`span_id`. The last two let a log line be found from its trace and a trace from its log line, so when
a trace backend exists the correlation is already there. By default everything goes to stdout as
JSON. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to a collector and logs, metrics, and traces ship over
OTLP/HTTP instead; nothing in your app changes. A Grafana / Tempo / Loki stack is not included yet;
`NEXT.md` names its trigger.

## What the platform team can and cannot see

The platform team sees all telemetry by default — logs, metrics, traces, audit records — and none of
your data. Reaching your data requires break-glass: a time-boxed grant, logged to an audit stream
your team can read. The approval step is a stub today.

Because telemetry is visible platform-wide, the logger only accepts scalar fields. Passing a dict, a
list, or a row raises `TypeError` at the call site, so a record cannot slip into a log line by
accident. The six required field names are reserved and raise `ValueError` if you pass them. It is
still your responsibility not to log a sensitive scalar — a salary is a number.

## When the SDK changes

Your app is on the SDK at `HEAD`; there is no version to bump. Every SDK pull request runs your app's
lint, types, `insights check`, and tests, and `CODEOWNERS` requests your review when the change
touches your directory. If a change cannot land with every app in one PR, the SDK owner ships a
compatibility shim first and removes it later. `scaffold_version` in your manifest is not yet used by
anything; it exists so a future `insights upgrade` can migrate generated files, which is deliberately
not built.

## The rules

| Rule                     | What                                                              | Why                                                       | ADR  |
|--------------------------|-------------------------------------------------------------------|-----------------------------------------------------------|------|
| `no-raw-drivers`         | No `psycopg`, `asyncpg`, `requests`, or `urllib.request` imports  | The SDK hands you a configured client; raw drivers bypass it | 0003 |
| `no-client-construction` | No `httpx.Client`, `httpx.get`, `create_engine`, etc.             | Construction is where credentials, timeouts, and audit attach | 0005 |
| `use-create-app`         | No `FastAPI(...)` in app code                                     | `create_app()` installs auth and the boot check           | 0003 |
| `no-private-imports`     | No `insights_platform` import with a `_`-prefixed segment         | Private modules are not part of the upgrade contract      | 0001 |
| `apps-independent`       | Apps do not import each other; the SDK does not import apps       | Tenants share a runtime, not code                         | 0004 |
| `manifest-valid`         | `platform.toml` has every key; name matches; connections are known | The manifest is what the platform reads first             | 0002 |
| `scaffold-supported`     | `scaffold_version` is within two minor versions of the current    | Old scaffolds are migrated, not carried forever           | 0001 |

## Getting help

The decisions behind all of this are in `docs/adr/`; the list of what was left out and why is
`NEXT.md`. The platform team owns `sdk/`, `.github/`, and `docs/adr/`, and reviews every change to
`platform.toml`.
