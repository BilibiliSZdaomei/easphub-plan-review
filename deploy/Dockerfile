# linux/amd64 manifests verified from Docker Hub; application image is not built yet.
ARG NODE_IMAGE=node:24.15.0-bookworm-slim@sha256:152aceace5c03e2597988763165ee33e3fd3633636db0fc983cd2e126b02cfde
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm@sha256:6e13e65c55e33adf203d77ee371cf8bf5d81bd4902ef07565721f46bf44917af
FROM ${NODE_IMAGE} AS frontend
ARG APP_BASE_PATH=/apps/plan-review
ENV APP_BASE_PATH=${APP_BASE_PATH}
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build -- --config vite.config.ts

FROM ${PYTHON_IMAGE} AS dependencies
WORKDIR /build
COPY requirements-linux.lock ./
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: --prefix=/install -r requirements-linux.lock

FROM ${PYTHON_IMAGE} AS production
ARG APP_BASE_PATH=/apps/plan-review
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 APP_DATA_DIR=/app/data APP_BASE_PATH=${APP_BASE_PATH} HOST=0.0.0.0 PORT=3350
ENV PLAN_REVIEW_DEMO=0 PLAN_REVIEW_WORKER=0
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --no-create-home app && mkdir /app/data && chown 10001:10001 /app/data
COPY --from=dependencies /install /usr/local
COPY backend ./backend
COPY scripts/serve_container.py scripts/run_worker.py scripts/healthcheck.py scripts/bootstrap.py scripts/restore_accounts.py scripts/backup_restore.py ./scripts/
COPY migrations ./migrations
COPY alembic.ini ./
COPY deploy/warehouses.example.json ./deploy/warehouses.example.json
COPY --from=frontend /build/dist ./frontend/dist
USER 10001:10001
EXPOSE 3350
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 CMD ["python","scripts/healthcheck.py","ready"]
CMD ["python","scripts/serve_container.py"]
