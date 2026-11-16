#!/bin/sh
# Bring the schema up to date, optionally seed, then hand over to the server.
#
# Migrations run here rather than in the application so that starting several
# app containers later does not have several of them racing to migrate.
set -e

echo "[entrypoint] applying database migrations"
alembic upgrade head

# Always: the variable registry is required for the app to work. Idempotent —
# it only adds entries that are missing. The demo account/project are added
# only when MLFL_SEED_DEMO=1 (never set that on a public deployment).
echo "[entrypoint] seeding the variable registry (demo: ${MLFL_SEED_DEMO:-0})"
python -m api.seed

echo "[entrypoint] starting: $*"
exec "$@"
