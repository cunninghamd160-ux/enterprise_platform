# finance-nightly-rollup

Insights Hub scheduled job owned by team `finance`. `run_job()` supplies config, data access,
observability, and the completion metric; this job only implements `main()`.

## Run

    uv sync
    uv run --env-file .env python -m finance_nightly_rollup.main

Exit code 0 means `main()` completed; anything else means it raised and the failure was logged.

## Verify

    uv run pytest apps/finance-nightly-rollup
    uv run insights check apps/finance-nightly-rollup

## Container

    docker build -f apps/finance-nightly-rollup/Dockerfile -t finance-nightly-rollup .

The build context is the repository root because the job depends on the SDK through the workspace.
