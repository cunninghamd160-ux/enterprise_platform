# Platform Engineering Exercise: Insights Hub

## The situation

You've joined a mid-size enterprise as a founding engineer on a new **platform team**. Today, several product teams each build small internal "insight apps" — dashboards, scheduled reports, data explorers — for their business stakeholders. Every team currently hand-rolls the same things: authentication, permissions, access to shared data sources, deployment, logging. It's slow, inconsistent, and increasingly hard to govern.

Your job: **design and build the platform substrate these teams will build on** — and prove it works by consuming it yourself.

## Context that should shape your design

Read these carefully. They are not flavor text; your design will be evaluated against them.

- **Every tenant is a team of employees.** The platform is internal-only. You have observability into what runs, and organizational recourse when a team misbehaves.
- **Scale:** ~5 consuming teams today, plausibly ~25 in two years.
- **The platform team is 2–3 engineers,** who also maintain, upgrade, and support everything they build.
- **Apps share common needs.** At minimum: authN/authZ (assume corporate SSO exists — stub it), access to shared *data connections* (e.g., a warehouse, an internal REST API — stub these with fixtures or fakes), a deployment story, and a baseline of observability (logs/metrics enough to actually operate).
- **Teams vary.** Some will ship interactive CRUD web apps; others, scheduled batch jobs.
- **One early tenant is the People Analytics team.** Their compensation data will be the most sensitive thing the platform holds, and their compliance partner will review your design before they onboard.

## What to build

1. **The platform substrate.** The form it takes is *your* decision — shared library, service(s), scaffold/template, CLI, or some mix. Repo layout (monorepo vs. multi-repo) is also your call. These choices are part of what we're evaluating, so make them deliberately.
2. **Two thin example apps that consume the platform: one interactive web app and one scheduled job.** Keep their functionality deliberately trivial — they exist to prove the consumption model, not to impress.
3. **3–5 ADRs** (Architecture Decision Records). Short is fine — context, decision, alternatives considered, consequences. Put your hardest calls here, especially the ones where two legitimate goals pulled against each other and you had to pick. What you chose *not* to build is as interesting as what you built.
4. **`ONBOARDING.md`** — written for a hypothetical new team ("team #6") joining the platform. Their literal day one: how they create an app, get auth and data access, deploy, and know it's healthy. Write it as the product doc it is.

## Questions your submission must answer somewhere

You can answer these in ADRs, the onboarding doc, or a README — but don't dodge them:

- **Reuse mechanism:** how does shared behavior reach the apps, and what is the *upgrade story* when you change it and 12 apps already depend on it?
- **Enforcement:** where do platform rules live (CI, lint, runtime, review process, convention), and how did you decide where each one goes?
- **Isolation:** what do tenants share, what don't they, and what facts about this environment drew that line?
- **Operator access:** what can the platform team itself see and do — in telemetry and in tenant data — and how is that access granted, constrained, and evidenced?
- **Deliberate omissions:** what did you consciously leave out, and what would trigger building it?

## How we'll read it

ADRs first, code second. This exercise exists to show us how you think, so a modest system whose ADRs surface the real tensions you hit — and take a defensible position on them — beats a feature-complete system with thin reasoning, every time. Working code matters as evidence that your design survives contact with reality; it is not the product being graded. If you find yourself choosing between finishing a feature and writing down a hard decision, write down the decision.

## Ground rules

- **Time budget: 10-12 hours.** We mean it. When you hit the budget, stop and write down what you'd do next and why — an unfinished system with a clear-eyed "here's the rest" beats a polished but shallow one. We score prioritization, not endurance.
- **Stack is your choice.** Use whatever you're fastest in. Stubs, fixtures, and fakes are encouraged everywhere real infrastructure would be (no cloud accounts, no real SSO, no real warehouse). It should run locally with minimal setup — a README with 2–3 commands.
- **AI tools are allowed.** Use whatever you normally would. Be aware that the follow-up session (below) is you, live, without prep time — the design needs to be *yours* in the sense that you can defend and extend it.

## What happens next

You'll walk us through your submission in a **~75-minute live session**: a short walkthrough, questions about your decisions, a changed requirement to work through, and a stretch where you sketch how you'd implement your answer against your own code.

To be transparent about how we evaluate: the submission qualifies you for this conversation and gives us something concrete to dig into — **the conversation itself is where most of the decision is made**. Build accordingly: a coherent, honest submission you can defend fluently beats a polished one you can't.

## Submitting

Send us a link to your repo(s) with a root `README.md` that maps everything: how to run it, where the ADRs are, where the onboarding doc is, and your "what I'd do next" notes.

Good luck — we're looking forward to seeing how you think.
