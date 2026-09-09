# people-analytics-dash

Insights Hub web app owned by team `people-analytics`. `create_app()` supplies auth, data access,
observability, health routes, the boot-time route check, and serves the built frontend; this app
only adds API routes under `/api` and pages under `frontend/src`.

## Run

    uv sync
    uv run --env-file .env uvicorn people_analytics_dash.main:app --reload

Requests carry the SSO stub headers, for example `X-Insights-User: you` and
`X-Insights-Team: people-analytics`. `/healthz` and `/readyz` need none. API routes live under `/api`.

## Frontend

`frontend/` is a Vite + React + TypeScript app. With the backend running:

    cd apps/people-analytics-dash/frontend
    npm ci
    npm run dev

The dev server proxies `/api` to `http://localhost:8000` and adds the SSO stub headers from
`.env.local` (`VITE_INSIGHTS_USER`, `VITE_INSIGHTS_TEAM`) to every proxied request, so the page
works with no proxy in front of it. In production the SSO proxy adds the headers and the dev
proxy is not involved.

    npm run lint
    npx tsc --noEmit
    npm run build
    npx vitest run

`npm run build` writes `frontend/dist`. When that directory exists, `create_app()` mounts it at `/`
during startup, after every route is registered, so `/api/*`, `/healthz`, and `/readyz` keep
precedence over the static files.

## Verify

    uv run pytest apps/people-analytics-dash
    uv run insights check apps/people-analytics-dash

## Container

    docker build -f apps/people-analytics-dash/Dockerfile -t people-analytics-dash .

The build context is the repository root because the app depends on the SDK through the workspace.
The Dockerfile builds the frontend in a `node` stage and copies `frontend/dist` into the Python
image, so the container serves the page at `/` and the API under `/api`.
