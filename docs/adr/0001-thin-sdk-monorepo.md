<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0001: Thin SDK, released and pinned, developed in a monorepo

**Status:** Proposed · **Date:** 2026-09-09

## Context

Five teams hand-roll auth, permissions, data access, deployment, and logging today; ~25 teams are
plausible in two years. The platform team is 2–3 engineers who also maintain, upgrade, and support
whatever they build. The brief asks how shared behavior reaches apps and what happens when a shared
change lands and twelve apps already depend on it.

The first tension is ownable surface versus tenant autonomy. Anything that runs as a service is a
control plane with an on-call rotation a team this size cannot sustain. Anything a team can copy and
fork drifts out of the platform's reach. What remains is a library with a small, enumerable
compatibility surface: the auth interface, the data-connection interface, the log schema, the config
contract.

The second tension is who absorbs the cost of a shared change. Two questions decide it, and they are
independent: does the platform keep the ability to *prove* a change against its dependents before
shipping, and does a tenant keep the ability to *choose when* to take it. Colocation answers the
first. Versioning answers the second. Conflating them forces a choice that does not need making.

## Decision

Thin SDK. Not a service, not a framework. The SDK is published as versioned, approved releases and
each app declares a pinned range; apps move between releases on their own schedule, within a
supported window of the current release minus two. Development stays in one repository as a `uv`
workspace, so CI runs every colocated app against the SDK at `HEAD` before a release is cut.

The monorepo is colocation, not coupling. Its job is pre-release proof, not forced simultaneity.

`uv` drops a declared version constraint when `[tool.uv.sources]` maps the dependency to a workspace
member: an app declaring `insights-platform>=9,<10` against a local `0.1.0` resolves and installs
`0.1.0` in silence. The pin is therefore a contract the workspace does not enforce, and a static
rule (`sdk-pin-declared`) has to — every app declares an explicit range, and the SDK's own version
must satisfy it. Built images resolve from the index, where the pin is real.

## Alternatives considered

**Workspace path dependencies, every app always on `HEAD`.** The upgrade is atomic: an SDK change
and the fixes to every dependent land in one PR. It is the right model at two to five apps and it is
what this repository did first. Rejected at the two-year target for three reasons: a regression that
passes CI reaches every app simultaneously with no canary, the platform team authors fix commits in
domain code it did not write and cannot always judge, and a tenant with a fixed release cadence has
no way to decline. The reversal is cheap in either direction — a per-app source override, four
lines — so this stays available for a tenant that wants it.

**Multi-repo with a published package.** The same release model as the decision above, minus the
colocation, and therefore minus the ability to run every dependent's tests before publishing. Every
release becomes a bet instead of a test run. Deferred rather than rejected: it is the correct end
state per tenant, and the trigger is a tenant the workspace cannot hold — one that is not Python, or
that needs a separate access boundary. `app-check.yml` is a `workflow_call` workflow so the gate
travels with them.

**Platform as a service / control plane.** Centralizes enforcement and makes upgrades instant and
unilateral, but is a 24/7 system in the request path of every tenant app, operated by 2–3 engineers
instead of built by them. Rejected on team size. The slice worth revisiting first is the data
gateway, because it would make ADR-0005's audit guarantee structural rather than review-backed.

**Framework.** Owns the app's structure and lifecycle, which makes every upgrade a migration, makes
every team's app look the same, and cannot onboard an app that already exists. Rejected: apps should
stay FastAPI apps or plain scripts.

## Consequences

Tenants get upgrade timing; the platform gets a canary. A release reaches one app before it reaches
twelve, which is the failure mode the atomic-PR model had no answer for.

The platform team takes on a release process it did not have: cutting and approving releases, a
changelog, a stated deprecation window, and security backports across the supported range.
Deprecation shims invert from exception to routine — a breaking change ships behind a shim in one
release and loses it two releases later, and the compatibility surface must stay small and
enumerable or that becomes the team's whole job.

Version skew becomes a real state. Up to three SDK versions run in production at once, so the
platform has to know the distribution: apps report their SDK version as a resource attribute, and
`scaffold-supported` and `sdk-pin-declared` are the checks that keep the tail bounded.

The manifest now carries two version facts that mean different things — `scaffold_version` is what
generated the app, the pyproject range is what it runs against — and ADR-0002's claim that the SDK
version is determined by the workspace no longer holds.
