<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0005: Operator access

**Status:** Proposed · **Date:** 2026-09-09

## Context

The platform team has to operate what runs: read logs, follow traces, diagnose failures. The
People Analytics compliance partner will review the design before onboarding and will ask what
the platform team can see, how that access is granted, constrained, and evidenced.

Operability needs telemetry. Compliance needs the platform team to not have ambient access to
compensation data. The hole between them is that logs are telemetry and an app can put data in a
log line.

## Decision

Platform team: all telemetry by default, no tenant data by default. Break-glass: time-boxed grant,
logged to an audit stream the tenant can read, stubbed approval.

## Alternatives considered

**Platform sees nothing.** Cleanest for compliance; the platform team cannot operate the system.
Rejected.

**Platform sees everything.** Simplest to operate; indefensible to a compliance reviewer for
compensation data. Rejected.

**Per-request approval for any tenant-data access.** Maximally evidenced, but turns every incident
into a ticket queue. Rejected in favor of time-boxed break-glass.

## Consequences

The logs-are-telemetry hole is closed by API shape: the structured logger accepts scalar fields
only (`Scalar` in the type signature, checked again at runtime), so a record cannot be passed
through as a field. Review backs this up. The hole is named, not hidden.

Audit coverage of data access is complete only because the SDK owns connection construction
(ADR-0003): `get_connection()` attaches audit hooks, credentials, timeouts, and instrumentation
in one place, so no query reaches a source without being evidenced. Break-glass friction slows
incident response; that cost is accepted. Approval is stubbed today — the evidence trail exists,
the approver does not yet.
