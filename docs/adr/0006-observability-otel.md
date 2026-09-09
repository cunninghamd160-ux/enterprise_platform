<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0006: Observability — OpenTelemetry as the wire contract

**Status:** Proposed · **Date:** 2026-09-09

## Context

The brief asks for enough logs and metrics to actually operate. ADR-0004 makes the telemetry
pipeline shared with per-tenant namespaces; ADR-0005 gives the platform team all of it by default.
Both assume a pipeline exists. This decision is what that pipeline speaks.

The tension is thinness versus neutrality. The SDK is meant to be thin. A vendor-neutral telemetry
seam is not free — it brings the OpenTelemetry SDK and its API churn along. The alternative is
picking two libraries today and locking the seam to them.

## Decision

OpenTelemetry is the wire contract for logs, metrics, and traces. Console exporter by default;
OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Required log fields: `app`, `team`, `principal`,
`request_id`, `trace_id`, `span_id`.

## Alternatives considered

**`structlog` + `prometheus_client` directly.** Lighter and well understood, but the seam is then
those two libraries and adding traces later means a second seam. Rejected on neutrality.

**A vendor SDK.** Best integration with one backend; locks every tenant to that backend and
makes the platform's choice the tenants' choice. Rejected.

**Logs only.** Smallest surface, but "know it's healthy" needs a counter and following a request
across a job and a warehouse call needs a trace. Rejected as insufficient to operate.

## Consequences

A Grafana/Tempo/Loki stack later is a compose profile and zero SDK change, because the seam is
already OTLP. Log-to-trace correlation works on day one because `trace_id` and `span_id` are in the
required schema. Console export by default means a fresh clone shows structured output with no
collector running.

The SDK carries OpenTelemetry's weight and tracks its API changes. Six required fields on every
record is a contract apps cannot opt out of.
