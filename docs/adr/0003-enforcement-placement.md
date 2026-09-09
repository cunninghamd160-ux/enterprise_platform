<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0003: Enforcement placement

**Status:** Proposed · **Date:** 2026-09-09

## Context

Platform rules can live in CI, lint, runtime, review, or convention. Each placement has a cost and a
failure mode: static checks are cheap but only see code; runtime checks are non-bypassable but add
coupling; review scales with reviewer attention; convention is free and fails silently.

One tenant holds compensation data. Whatever protects it cannot rest on convention. Everything else
should sit in the cheapest layer that is sufficient.

## Decision

Structural rules → static checks: one rule set in `insights_platform.check`, versioned with the
SDK, three entry points (pre-commit, `insights check`, CI). AuthZ and data access → runtime,
non-bypassable, guaranteed at construction (`create_app()`, `get_connection()`). Review process →
CODEOWNERS. Convention → only where wrong is recoverable.

## Alternatives considered

**Everything at runtime.** Maximally non-bypassable, but every rule becomes SDK coupling and
failures surface after deploy. Rejected: static is sufficient for structural rules.

**Everything in review.** No tooling, but attention does not scale to 25 tenants and a reviewer
cannot see a bypass in a file they were not shown. Rejected as the primary layer.

**`import-linter` for the import rules.** A known tool, but its contract config lives in the root
`pyproject.toml`, outside the SDK package, so rules would not be versioned with the SDK. Rejected.

## Consequences

Rules live in the SDK and reach apps the way any SDK change does. `insights check` globs `apps/*`,
so a new app is covered the moment it exists. Every rule message cites the ADR it enforces.

Review has two forms and they are not interchangeable. `insights check` is deterministic,
enumerable and versioned with the SDK: the same verdict on the same input in pre-commit, the CLI and
CI, each message citing the ADR it enforces. An agent reading a diff is none of those — its verdict
moves with the model and the prompt, its coverage cannot be listed, and it is versioned with
nothing. They also catch different classes. A check settles what an AST or a manifest can settle: a
raw driver import, an undeclared pin, a missing manifest key. An agent is for judgement no rule
expresses — an endpoint whose authZ marker is present but wrong for what it returns, a log line that
is schema-legal and still carries compensation data, structure drifted far enough from the scaffold
to be worth a question (ADR-0002).

The placement rule follows from that: a gate has to be deterministic. Anything that must not happen
belongs in a static rule or at construction, never in an agent, because an agent turns a guarantee
into a likelihood. ADR-0005's named hole is the worked example — the answer is a schema-only logger,
not a reviewer told to watch for leaked data. An agent sits under CODEOWNERS as a third review
position: it widens what review notices, it does not raise what review guarantees.

Static checks catch accidental and lazy bypass, not adversarial bypass, and do not claim to;
adversarial is handled by ADR-0004's environment facts plus review. Pre-commit hooks are a
convenience; CI plus branch protection is the authoritative gate. Runtime enforcement at
construction means apps must use `create_app()` and `get_connection()` — that SDK coupling is
the price of the non-bypassable guarantee.
