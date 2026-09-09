# ADR-0006: Observability — OpenTelemetry as the wire contract

**Status:** Proposed · **Date:** 2026-09-09

## Context

## Decision

OpenTelemetry is the wire contract for logs, metrics, and traces. Console exporter by default;
OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Required log fields: `app`, `team`, `principal`,
`request_id`, `trace_id`, `span_id`.

## Alternatives considered

## Consequences
