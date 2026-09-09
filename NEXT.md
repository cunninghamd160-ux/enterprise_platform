# Next

What was consciously left out, and what would trigger building it. Running list during the build;
cleaned up at the end.

## Deliberate omissions

| Omission | Trigger to build it |
|----------|---------------------|
| Real Kubernetes manifests | First environment that isn't a single compose host |
| Secrets manager integration | First real credential; today every value is a fixture |
| Service mesh | Never at 5–25 tenants on one shared runtime; revisit if tenants leave it |
| Self-service portal UI | ~15 tenants, when scaffold support exceeds an engineer-week per month |
| Multi-region | A tenant with a data-residency requirement |
| `insights upgrade` | ~12 apps, when hand-migrating between scaffold versions is the biggest time sink |
| `insights deploy` | When the compose-based path stops matching how prod actually deploys |
| Grafana / Tempo / Loki compose profile | First time someone needs to look at a trace rather than grep a log; the seam is already OTLP, so this is zero SDK change |
| Circuit breaker / retry policy on connections | First partial outage of a shared source; `get_connection` owns construction, so this lands in one place |
| Static mirror of the route-authZ check | When someone wants it in pre-commit; the runtime boot check is sufficient until then |
| Deprecation shim tooling | First SDK change that cannot land in one PR with all dependents |
| `import-linter` | Considered and rejected: contract config would live outside the SDK package, so rules would not be versioned with the SDK |

## Found during the build

## Tools

The data-connection registry is the natural seam to expose connections as tools later; nothing in
this repo does so.
