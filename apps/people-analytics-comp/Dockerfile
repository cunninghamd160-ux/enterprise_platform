FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY . .
RUN uv sync --frozen --no-dev --package people-analytics-comp
ENV PATH="/workspace/.venv/bin:$PATH"
WORKDIR /workspace/apps/people-analytics-comp
EXPOSE 8000
CMD ["uvicorn", "people_analytics_comp.main:app", "--host", "0.0.0.0", "--port", "8000"]
