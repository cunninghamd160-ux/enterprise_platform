# ADR-0003: Enforcement placement

**Status:** Proposed · **Date:** 2026-09-09

## Context

## Decision

Structural rules → static checks: one rule set in `insights_platform.check`, versioned with the
SDK, three entry points (pre-commit, `insights check`, CI). AuthZ and data access → runtime,
non-bypassable, guaranteed at construction (`create_app()`, `get_connection()`). Review process →
CODEOWNERS. Convention → only where wrong is recoverable.

## Alternatives considered

## Consequences
