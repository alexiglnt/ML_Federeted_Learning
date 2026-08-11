# Smoke tests

Black-box checks that run against a live site. They use nothing but the Python
standard library, so no test dependency has to be installed and nothing rots:

```bash
docker compose up -d --build      # site on :8000
python tests/smoke_lot0.py        # foundations: auth, registry, column matching
python tests/smoke_lot1.py        # projects: creation, validation, permissions
```

Each exits non-zero on the first failure and prints a PASS/FAIL line per check.

## What these are, and are not

They are not unit tests. They assert the behaviours that are **load-bearing and
would fail silently** — the list in ARCHITECTURE.md §8 — rather than trying for
coverage. Specifically:

- column headings written `γ (°)` and `rβ (µm)` still match the registry (they
  are the literal headings in the source study, so this is the case that
  matters);
- the login form gives one message for a wrong password and for an unknown
  account, so it cannot be used to test whether a researcher has an account;
- input order survives a round trip, because permuted columns fit silently
  wrong coefficients;
- a variable cannot be both an input and a target of one project;
- a proposed registry variable is usable by its proposer and by nobody else;
- the permission matrix holds for anonymous visitors, other signed-in users and
  the owner.

**They write to the database they run against.** Accounts and projects are
tagged with a random suffix so repeated runs do not collide, but they
accumulate. Run them against a development instance, and reset it when the
clutter bothers you:

```bash
docker compose down -v && docker compose up -d --build
```

## Still to write

The two invariants that cannot be tested until the code they guard exists —
both from ARCHITECTURE.md §8, and both silent failures:

1. aggregating from summed sufficient statistics equals fitting on pooled raw
   data (lot 2; the pre-rebuild `legacy/tests/check_aggregation.py` checked
   exactly this to 1e-13 and is worth porting rather than rewriting);
2. switching a contribution from federated to shared does not double-count its
   data (lot 5b).
