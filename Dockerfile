FROM node:22-bookworm-slim AS web-builder

WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY --from=web-builder /app/src/enterprise_llm_proxy/static/ui ./src/enterprise_llm_proxy/static/ui

RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# Build routerctl wheel for distribution to developers
RUN uv build --wheel --out-dir /app/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "enterprise_llm_proxy.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
