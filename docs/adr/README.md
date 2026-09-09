# Architecture Decision Records

Each record is short: context, decision, alternatives considered, consequences. Each names the
tension it resolves and the trade-off it accepts.

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-thin-sdk-monorepo.md) | Thin SDK, released and pinned, developed in a monorepo | Proposed |
| [0002](0002-generate-dont-clone.md) | Generate, don't clone | Proposed |
| [0003](0003-enforcement-placement.md) | Enforcement placement | Proposed |
| [0004](0004-tenant-isolation.md) | Tenant isolation | Proposed |
| [0005](0005-operator-access.md) | Operator access | Proposed |
| [0006](0006-observability-otel.md) | Observability: OpenTelemetry as the wire contract | Proposed |

The set is kept to the six hardest calls. Three later decisions — the async-only data seam, owned
per-app databases, and the co-located frontend — are consequences of ADR-0001 and ADR-0004 and are
recorded in `BACKLOG.md` (EA, E2, E6) and `NEXT.md` rather than as ADRs of their own.
