# ADR-0004: Tenant isolation

**Status:** Proposed · **Date:** 2026-09-09

## Context

## Decision

Shared: runtime, telemetry pipeline, deploy path, SSO. Per-tenant: data-connection credentials
(resolved by name at startup from the app's own environment), log/metric/trace namespaces, authZ
policy.

## Alternatives considered

## Consequences
