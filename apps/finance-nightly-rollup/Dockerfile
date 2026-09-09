FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY . .
RUN uv sync --frozen --no-dev --package finance-nightly-rollup
ENV PATH="/workspace/.venv/bin:$PATH"
WORKDIR /workspace/apps/finance-nightly-rollup
CMD ["python", "-m", "finance_nightly_rollup.main"]
