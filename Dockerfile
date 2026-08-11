# Two stages: compile the front end with Node, then run it from Python.
#
# Building the front end *inside the image* is deliberate (ARCHITECTURE.md
# §2.1). The realistic future of this repository is a cold restart months from
# now, and requiring a working local Node toolchain at that point is how such a
# restart fails. `docker compose up --build` is the whole contract.

# --------------------------------------------------------------------------- #
# 1. Front end
# --------------------------------------------------------------------------- #
FROM node:20-alpine AS web

WORKDIR /build

# Dependencies first: this layer is cached and only invalidated when the
# lockfile changes, so an ordinary source edit does not reinstall the world.
COPY web/package.json web/package-lock.json ./
# `npm ci` installs the lockfile exactly, and fails rather than silently
# resolving a newer version. That is the point of committing the lockfile.
RUN npm ci

COPY web/ ./
RUN npm run build

# --------------------------------------------------------------------------- #
# 2. API and runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/ api/
COPY alembic.ini ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

COPY --from=web /build/dist web/dist

# Runs as a non-root user: a bug in file upload handling should not be a bug
# with root's privileges.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/var/data \
    && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
