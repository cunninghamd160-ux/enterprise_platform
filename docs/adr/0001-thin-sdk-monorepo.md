<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0001: Thin SDK in a `uv` workspace monorepo

**Status:** Proposed · **Date:** 2026-09-09

## Context

Five teams hand-roll auth, permissions, data access, deployment, and logging today; ~25 teams are
plausible in two years. The platform team is 2–3 engineers who also maintain, upgrade, and support
whatever they build. The brief asks how shared behavior reaches apps and what happens when a shared
change lands and twelve apps already depend on it.

The tension is ownable surface versus tenant autonomy. Anything that runs as a service is a control
plane with an on-call rotation a team this size cannot sustain. Anything a team can copy and fork
drifts out of the platform's reach. What remains is a library with a small, enumerable compatibility
surface: the auth interface, the data-connection interface, the log schema, the config contract.

## Decision

Thin SDK in a `uv` workspace monorepo. Not a service, not a framework. Apps depend on the SDK by
workspace path and are always on HEAD.

## Alternatives considered

**Platform as a service / control plane.** Centralizes enforcement and upgrades, but is a 24/7
system that 2–3 engineers would be operating instead of building. Rejected on team size.

**Framework.** Owns the app's structure and lifecycle, which makes every upgrade a migration and
every team's app look the same. Rejected: apps should stay FastAPI apps or plain scripts.

**Multi-repo with a published package.** Gives each team upgrade timing, but the version matrix
grows with tenant count and the platform cannot prove an SDK change against dependents before
publishing. Rejected at this scale; the `workflow_call` check workflow is the exit ramp if a team
must leave the monorepo later.

## Consequences

The upgrade story is atomic: an SDK change and the fixes to every dependent land in one PR, CI runs
every app's tests, and CODEOWNERS pulls each affected team into review. Deprecation shims are only
for the change that cannot land in one PR.

Tenants give up upgrade timing; they are always on HEAD. The compatibility surface must stay small
and enumerable or the atomic-PR model stops scaling. The CLI and the check rules become platform
code that the same 2–3 engineers own.
