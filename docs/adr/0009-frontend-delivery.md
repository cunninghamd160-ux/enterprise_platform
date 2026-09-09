<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0009: Frontend delivery

**Status:** Proposed · **Date:** 2026-09-09

## Context

The brief's web apps are interactive: a team wants a page, not only JSON. The question is where
that page lives, who serves it, and how it reaches the API without a second auth story. The
platform team is 2–3 engineers, so a second runtime or image per app is a cost that scales with
tenant count, while a page that lives next to its API is one deploy unit that already has SSO,
health routes, and a container.

## Decision

A co-located single-page app served by its own app under `/`, API under `/api`. `insights new
--kind web` generates `frontend/` (Vite + React + TypeScript); `create_app()` mounts `frontend/dist`
at `/` during startup, after every route is registered, so API routes and `/healthz`/`/readyz` keep
precedence. One Dockerfile builds the page in a `node` stage and the Python image serves it. In
development the Vite proxy forwards `/api` to the backend and adds the SSO stub headers; in
production the SSO proxy does. `--no-frontend` produces an API-only app; jobs never get one.

## Alternatives considered

**Separate frontend service and image.** Independent deploys and a CDN-shaped path, but a second
runtime, a CORS story, and a second place SSO must be wired. Rejected at this team size.

**Server-side rendering.** No client build, but ties the page to Python templating and gives up
the component ecosystem teams already know. Rejected.

**A shared portal hosting every app's UI.** One place to log in, but it is a control plane the
platform team operates. This is the self-service portal in `NEXT.md`, with its own trigger.

## Consequences

The static mount is not an `APIRoute`: `check_routes` ignores it and no authorization marker
applies to static assets, so the page shell is reachable by anyone who reaches the host; data stays
behind the marked `/api` routes. `StaticFiles(html=True)` serves `index.html` at `/` only, so deep
links to client-side routes are 404 until a fallback is added. The request counter labels static
requests `unmatched`. Per-app CI roughly doubles when a frontend exists (node setup plus `npm ci`).
Token substitution stays conditional-free (ADR-0002): `--no-frontend` drops `frontend/**` and swaps
in `<file>.no-frontend.tmpl` variants for the Dockerfile and README.
