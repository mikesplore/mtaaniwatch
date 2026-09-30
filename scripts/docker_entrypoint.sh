#!/bin/sh
# Bring the container's database up to date, load the demo records, then serve.
set -e

PORT="${PORT:-9002}"
SEED_DEMO_DATA="${SEED_DEMO_DATA:-true}"

echo "Applying database migrations..."
alembic upgrade head

if [ "${SEED_DEMO_DATA}" = "true" ]; then
  echo "Loading demo areas, crews, and reports..."
  # Seeding is idempotent, but a demo dataset is not worth blocking the API
  # over: report the failure and let the coordinator dashboard start empty.
  if ! python -m scripts.seed_demo_data; then
    echo "WARNING: demo seed failed; starting the API without demo records." >&2
  fi
else
  echo "SEED_DEMO_DATA=${SEED_DEMO_DATA}; skipping demo records."
fi

echo "Starting MtaaniWatch on port ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
