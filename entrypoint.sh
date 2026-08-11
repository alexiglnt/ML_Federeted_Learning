#!/bin/sh
# Bring the schema up to date, optionally seed, then hand over to the server.
#
# Migrations run here rather than in the application so that starting several
# app containers later does not have several of them racing to migrate.
set -e

echo "[entrypoint] applying database migrations"
alembic upgrade head

if [ "${MLFL_SEED_ON_START}" = "1" ]; then
  # Idempotent: it fills an empty database and does nothing to a populated one.
  echo "[entrypoint] seeding (no-op if the database already has content)"
  python -m api.seed
fi

echo "[entrypoint] starting: $*"
exec "$@"
