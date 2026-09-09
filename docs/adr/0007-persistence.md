<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0007: Persistence

**Status:** Proposed · **Date:** 2026-09-09

## Context

The brief asks for interactive CRUD web apps, and until now an app had nowhere to write: every
connection the platform hands out is a read-only view of a shared source. A store an app owns is a
per-tenant resource, so it sits under ADR-0004's isolation line — per-app credentials, per-app
database, platform-owned construction — and its schema must change without hand-typed DDL.

## Decision

Owned stores are per-app Postgres databases behind SDK-constructed async engines; shared stores stay
read-only connections. An app opts in with `[database] enabled = true` in `platform.toml`; the
platform resolves `INSIGHTS_DB_URL` (one role and one database per app), builds the engine with the
same timeouts, audit hook, and instrumentation `get_connection()` attaches, and offers
`db.get_session()` as the FastAPI dependency and `db.Base` for models. Schema changes are Alembic
migrations under `apps/<name>/migrations/`, driven by `insights db revision|upgrade|current`; no app
carries an `alembic.ini` or imports Alembic (`no-raw-alembic`). SQLite is the fixture: at startup
the SDK creates the schema from the models so tests need no migration step; a Postgres database is
never touched by an app process — `insights db upgrade` is the only path.

## Alternatives considered

**One shared database with a schema per app.** Fewer moving parts, but the isolation line becomes
a `search_path`, and one misconfigured role reads another tenant's tables. Rejected.

**App-managed connection strings.** Lets a team choose its store, but construction is where
credentials, timeouts, audit, and instrumentation attach (ADR-0005); a hand-built engine skips all
four. Rejected.

**No owned persistence; apps call APIs only.** Nothing to migrate or back up, but the brief's CRUD
apps have nowhere to write and each team hand-rolls a service to hold state. Rejected.

## Consequences

Every write flushes through a session the platform constructed, so the audit stream records
`data.write` with the table name and row count and never a value. Two schema paths exist on purpose
— models on SQLite, migrations on Postgres — so a unit test cannot prove a migration; the
`integration` marker runs against compose Postgres for that. The FastAPI dependency commits after
the response is sent, so a repository that needs a generated id, or must surface a constraint error
as a 500, flushes inside the route. Migrations import the app to register its models, which boots
`create_app()` in the CLI. TLS on non-local URLs is not enforced yet; ADR-0008 will add it.
