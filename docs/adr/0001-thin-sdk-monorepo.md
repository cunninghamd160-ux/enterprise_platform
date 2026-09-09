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
state per tenant, and the trigger is a tenant the workspace cannot hold — one that needs a separate
access boundary, or whose release cadence the support window cannot absorb. A tenant that is not
Python is not this trigger: a published Python package is no more importable from Node than a
workspace path is. `app-check.yml` is a `workflow_call` workflow so the gate travels with them.

**Platform as a service / control plane.** Centralizes enforcement and makes upgrades instant and
unilateral, but is a 24/7 system in the request path of every tenant app, operated by 2–3 engineers
instead of built by them. The cost is not the network hop; it is shared fate and capacity planning,
and that a control plane has to be made highly available by someone. Rejected on team size.

**Sidecar.** The same enforcement as a control plane, but a copy runs beside each app instance
rather than as one shared service: calls are localhost, failure is per-pod instead of fleet-wide,
and the thing scales with the app rather than being capacity-planned. That property, not the
localhost hop, is what makes it affordable to a team this size — it needs no rotation, because its
alerts are the app's alerts. It is also not one decision but four. Observability → viable today at
zero SDK change, an OTel Collector sidecar, because ADR-0006 already makes OTLP the wire contract.
SSO → viable, because `sso.py` is already headers to a `Principal`, so a proxy that authenticates
and sets those headers is a configuration swap. Data access → the valuable one, because a proxy
holding the credentials would make ADR-0005's audit guarantee structural rather than review-backed,
and the expensive one, because it has to speak the database's wire protocol. AuthZ → not viable,
because ADR-0003's check runs at boot against the app's route table and a sidecar does not have it.

Deferred on a precondition rather than a judgement: a sidecar needs a runtime that co-schedules
containers, and this platform is compose on a single host, so it inherits the trigger already
recorded against real Kubernetes. Three things would pull it forward — a tenant that is not Python,
since moving enforcement out of the process is the only thing that reaches a language the SDK
cannot; a security fix that must cross the fleet without twenty-five teams raising a pull request;
and enforcement that has to survive an app that is not cooperating, which ADR-0003 says plainly the
static rules do not. It would not replace the SDK. The end state is a thinner SDK for ergonomics in
front of a sidecar that holds the credentials, which means this SDK's enforcement claims are
load-bearing today precisely because there is no sidecar to hold them.

**Framework.** The line is inversion of control: a library is called, a framework calls you and owns
the entrypoint, the file layout, and the lifecycle. Two tests settle it here. Delete the platform —
an app built on a library is still an app that fails to import, an app built on a framework is
handlers with nothing left to attach them to. Adopt it into an app that already exists — `FastAPI()`
becomes `create_app()`, where a framework needs a rewrite, and five teams already have apps.
Rejected on both, and on the fact that every lifecycle change would become a migration.

The SDK is not innocent of lifecycle: `create_app()` installs middleware and health routes, and
`run_job()` owns the context, the metrics, and the exit code. What keeps it a library is that
`create_app()` is a factory handing back a plain `FastAPI` the app then decorates, and that the app
still writes its own `__main__` and passes `run_job` a single callable. The one place the SDK does
behave like a framework is the boot-time route check, which refuses to start an app that left a
route unmarked. That is deliberate and argued in ADR-0003, and it is the exception that shows where
the line is.

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

An app now carries two version facts that mean different things and move independently:
`scaffold_version` in the manifest is what generated it, the range in its `pyproject.toml` is what
it runs against. Keeping them separate is what lets a team fall behind on the scaffold without
falling behind on the SDK, and ADR-0002 records only the first for that reason.
