# Insights Hub

Paved road for internal insight apps: a thin Python SDK, a scaffold CLI, enforcement rules, and a
deployment template. Apps stay FastAPI apps or plain scripts; the platform owns the cross-cutting
seams — auth, permissions, data access, observability, deploy.

**Status: skeleton.** [SCOPE.md](SCOPE.md) is the plan, [docs/adr](docs/adr/) holds the decisions,
[NEXT.md](NEXT.md) holds what's deferred and why.

## Run

```sh
uv sync
uv run pytest
```
