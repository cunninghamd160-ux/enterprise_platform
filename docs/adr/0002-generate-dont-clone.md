<!-- DRAFT: author rewrites every sentence before submission (SCOPE rule 2) -->
# ADR-0002: Generate, don't clone

**Status:** Proposed · **Date:** 2026-09-09

## Context

Team #6 needs a runnable app on day one with auth, a data connection, logging, and a deploy entry
already wired. The question is where that starting point lives and how the platform knows, months
later, what shape a given app was born in.

A template a team clones is frozen at clone time. Every subsequent improvement to the template is
invisible to apps already created, and the platform has no record of which version each app started
from. That record is the one fact a future migration tool needs.

## Decision

`insights new` copies a template from inside the SDK package and substitutes `__NAME__`. It
records `scaffold_version` in `platform.toml`.

## Alternatives considered

**Cookiecutter or a cloned template repo.** Familiar, but the template lives outside the SDK and
drifts from it; nothing records which version produced an app. Rejected on drift.

**A template engine inside the CLI.** More expressive than token substitution, but a second
language to maintain for five files. Rejected: copy-and-substitute is enough (the EMES
`scaffold-handler.ps1` precedent works the same way).

**No scaffold; documentation only.** Zero code to maintain, but every team re-derives the same
five files and the platform cannot check they did it right. Rejected on onboarding cost.

## Consequences

Templates ship inside the SDK package and are versioned with it, so improving the template is an
SDK change like any other. `scaffold_version` records what generated the app, which is a different fact from the SDK
release the app runs against: that one is the pinned range in its `pyproject.toml`
([ADR-0001](0001-thin-sdk-monorepo.md)). An app can sit two scaffold versions behind and still
be pinned to the current SDK, so the manifest records only the first.

The CLI is one more thing to maintain. Token substitution cannot express conditional structure; if
the `web` and `job` templates ever need more than a name, this decision gets revisited.
