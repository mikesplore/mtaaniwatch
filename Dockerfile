FROM node:22-alpine AS frontend-build

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./
COPY --from=frontend-build /frontend/dist ./frontend/dist

RUN pip install --no-cache-dir . \
    && sed -i 's/\r$//' ./scripts/docker_entrypoint.sh \
    && chmod +x ./scripts/docker_entrypoint.sh

# Seeding runs on start so a fresh container has demo areas, crews, and reports.
# Set SEED_DEMO_DATA=false to start against real data only.
ENV SEED_DEMO_DATA=true \
    PORT=9002

EXPOSE 9002

CMD ["./scripts/docker_entrypoint.sh"]
