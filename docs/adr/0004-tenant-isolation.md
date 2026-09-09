<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0004: Tenant isolation

**Status:** Proposed · **Date:** 2026-09-09

## Context

Every tenant is a team of employees. The platform is internal-only, the platform team can see what
runs, and there is organizational recourse when a team misbehaves. Scale is ~5 tenants today,
plausibly ~25 in two years. One early tenant, People Analytics, holds compensation data.

Two facts pull in opposite directions. Internal employees with org recourse do not need SaaS-grade
blast-radius isolation between tenants. Compensation data does need hard, runtime-enforced control
over who can reach it. Both facts are true at once; the line between shared and per-tenant has to
honor both.

## Decision

Shared: runtime, telemetry pipeline, deploy path, SSO. Per-tenant: data-connection credentials
(resolved by name at startup from the app's own environment), log/metric/trace namespaces, authZ
policy.

## Alternatives considered

**Per-tenant runtime.** Eliminates noisy-neighbor risk, but multiplies what 2–3 engineers operate
by tenant count. Rejected at 5–25 tenants.

**Per-tenant deploy pipelines.** Gives teams independence, but the deploy path is where credential
scoping is enforced; fragmenting it fragments the guarantee. Rejected.

**Full multi-tenancy isolation (SaaS-grade).** Defensible for external customers; not justified
when every tenant is an employee and recourse exists. Rejected on the environment's facts.

## Consequences

Noisy-neighbor risk on the shared runtime is accepted at this scale. An app can only reach
connections it declares, and credentials are resolved from that app's own environment at startup —
deploy-time credential scoping is what stops an adversarial bypass, not static analysis. Telemetry
namespaces are per-tenant so the shared pipeline can still be filtered by team.

If either founding fact changes — tenants stop being employees, or a tenant needs isolation beyond
data access — this line moves.
