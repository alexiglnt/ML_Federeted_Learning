# Machining model platform

Pool machining measurements across labs, and share the models they produce.

A researcher measuring residual stress on Ti-6Al-4V may have **seven**
conditions. Each one costs machine time, money and effort, so models in this
field get fitted on almost nothing and generalise accordingly. This platform
lets anyone declare what they measure, upload their own data to get a model,
and lets researchers measuring the same quantities contribute theirs to improve
it — receiving access to the model in exchange.

> **Status: under construction. Not deployed, and not ready for public use.**
> [ROADMAP.md](ROADMAP.md) lists what exists, what does not, and the legal and
> technical blockers that must be cleared before this goes online.

## Run it

```bash
docker compose up --build
```

Then <http://localhost:8000>.

That is the whole contract — no local Node, no local Python. The front end is
compiled inside the Dockerfile deliberately; see
[ARCHITECTURE.md](ARCHITECTURE.md) §2.1 for why, because it is the sort of
decision that looks like an inconvenience until someone tries to restart this
project cold a year from now.

On an empty database the entrypoint applies migrations and seeds the variable
registry plus a demo project. A demo account is created with a published
password — fine locally, unacceptable in production, and noted as such in the
roadmap.

## Documents

| | |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it fits together and **why**. Start at §5 — the mathematics is the only genuinely subtle part, and §5.4 and §5.5 describe failures that are silent rather than loud. |
| [ROADMAP.md](ROADMAP.md) | Build status, known gaps, and the blockers before going live. |
| [legacy/](legacy/) | The pre-rebuild site, kept whole. |

## What is in the tree

```
api/            FastAPI application
  models.py     the data model — the spine of everything
  deps.py       the permission matrix, in one place so it can be tested
  services/     column matching, and (to come) file parsing and training
  migrations/   Alembic
  seed.py       registry and demo project
web/            React + Vite + TypeScript front end
legacy/         the original single-model site, preserved
```

## `legacy/` — what it is and why it is kept

This repository began as something narrower: one hardcoded model (Ti-6Al-4V,
four inputs, two residual-stress targets) whose distinguishing feature was that
the fitting ran **in the contributor's browser**. Only summary statistics were
transmitted, so measurements never left the contributor's machine.

That mode survives in the new platform as a contributor's choice — improve the
model without disclosing your data, and forgo access to the model in return.
The working implementation, its exactness tests and its own README are kept in
`legacy/` rather than left to git archaeology, because rewiring them is a
scheduled task (lot 5b) and reinventing them would be a waste. Its comments
were written in French and are translated as each piece is ported.
