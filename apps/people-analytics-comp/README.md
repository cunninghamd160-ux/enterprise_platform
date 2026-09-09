# people-analytics-comp

Insights Hub web app owned by team `people-analytics`. `create_app()` supplies auth, data access,
observability, health routes, and the boot-time route check; this app only adds routes.

## Run

    uv sync
    uv run --env-file .env uvicorn people_analytics_comp.main:app --reload

Requests carry the SSO stub headers, for example `X-Insights-User: you` and
`X-Insights-Team: people-analytics`. `/healthz` and `/readyz` need none. `GET /comp` returns
compensation rows and is limited to `X-Insights-Team: people-analytics`; every query it makes is
audited by the SDK with the principal and a hash of the statement, never the statement itself.

## Verify

    uv run pytest apps/people-analytics-comp
    uv run insights check apps/people-analytics-comp

## Container

    docker build -f apps/people-analytics-comp/Dockerfile -t people-analytics-comp .

The build context is the repository root because the app depends on the SDK through the workspace.
