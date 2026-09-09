FROM node:24-alpine AS frontend
WORKDIR /fe
COPY apps/people-analytics-dash/frontend/package.json apps/people-analytics-dash/frontend/package-lock.json ./
RUN npm ci
COPY apps/people-analytics-dash/frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY . .
COPY --from=frontend /fe/dist apps/people-analytics-dash/frontend/dist
RUN uv sync --frozen --no-dev --package people-analytics-dash
ENV PATH="/workspace/.venv/bin:$PATH"
WORKDIR /workspace/apps/people-analytics-dash
EXPOSE 8000
CMD ["uvicorn", "people_analytics_dash.main:app", "--host", "0.0.0.0", "--port", "8000"]
