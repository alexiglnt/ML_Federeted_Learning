# Smoke tests

Black-box checks that run against a live site. They use nothing but the Python
standard library, so no test dependency has to be installed and nothing rots:

```bash
docker compose up -d --build      # site on :8000

# Over HTTP, from outside the container.
python tests/smoke_lot0.py        # foundations: auth, registry, column matching
python tests/smoke_lot1.py        # projects: creation, validation, permissions
python tests/smoke_lot2a.py       # uploads: file reading, mapping, validation
python tests/smoke_lot2b.py       # training: versions, lineage, who sees the model
python tests/smoke_lot3.py        # project page: validity domain, prediction, export, audit
python tests/smoke_lot4.py        # discovery: facets, and ranking projects against a file
python tests/smoke_lot5.py        # review: the two scores, access granted and taken away

# Inside the container — these need numpy and the api package, not a server.
docker compose exec app python tests/check_aggregation.py
docker compose exec app python tests/check_engines.py
```

Each prints a PASS/FAIL line per check and exits non-zero if any failed.

`smoke_lot2a.py` is the one exception to the no-dependencies rule: it needs
`openpyxl` to build the spreadsheet fixture it uploads (`pip install openpyxl`).
The server dependency is already pinned; this is only for generating the test
file.

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
  the owner;
- a European Excel export — two title rows, semicolons, decimal commas, Greek
  headings — is read correctly end to end;
- the same file cannot be submitted twice to one project, and a staged upload
  cannot be claimed by a different user;
- data outside a project's declared range **warns and does not block**, because
  measurements from an uncovered regime are the most valuable contribution
  there is;
- pending contributions do not inflate a project's row count or widen its
  published validity domain;
- **fitting on summed sufficient statistics equals fitting on the pooled rows**
  — checked to about 1e-11 at a condition number of 1.7e5, for least squares
  and for PIML at every lambda. This is the claim the federated design rests
  on, and if it ever stops holding nothing would look broken;
- `subtract` undoes `add` exactly, which is what makes the double-counting trap
  in ARCHITECTURE.md §5.5 fixable at all;
- physical priors bite where the data contradicts them and cost **nothing**
  where the data already agrees — if the second half fails, every fit is
  quietly biased;
- leave-one-lab-out is harsher than ordinary cross-validation when one lab
  diverges (0.17 against 0.63) and close to it when labs agree (0.997 against
  0.997), so it is neither decorative nor pessimistic by construction;
- coefficients and equations are withheld from anonymous visitors and from
  signed-in non-contributors, while metrics stay public;
- the extrapolation warning is measured against the range there is **data** for
  and not against the declared range — the test declares a maximum of 75, holds
  data only to 60, and asserts the warning quotes 60, because a model trusted
  over a range nobody measured is the failure this whole feature exists to
  prevent;
- prediction and export are refused to a **pending** contributor. Submitting is
  not being accepted, and if this ever inverts, uploading noise unlocks models;
- a contributor cannot download another contributor's file, and the access log
  shows each of them only the reads of their own data while the owner sees all
  of them;
- a spreadsheet formula in a downloaded CSV comes back neutralised while
  negative measurements, which begin with the same character, come back
  untouched. Both halves matter: the second one failing corrupts real data;
- **accepting a contribution grants model access and rejecting or withdrawing
  it takes that access away** — unless the same person still has other accepted
  data on the project. If revocation ever stops working, a contributor can
  unlock a model and then pull their data back out, which is the free ride the
  review step exists to prevent. It broke exactly this way during the build and
  this check is what caught it;
- a rejected or withdrawn contribution leaves **no trace** in the next trained
  version (ARCHITECTURE.md §8.4), asserted against the version's lineage;
- the two scores of §5.3 diverge the way the document says they will. The test
  builds the case that matters — data from a regime the model cannot reach,
  generated exactly linearly — and asserts the refit score is excellent while
  the transfer score is far worse. That pattern marks the most valuable kind of
  contribution there is, and an owner reading transfer alone would reject it;
- model access is not file access: a fully accepted contributor still cannot
  read another contributor's file;
- the owner cannot reinstate a contribution the contributor withdrew;
- **matching a file against the platform stores nothing** — after a match, the
  project's row count, contribution list and version list are all unchanged.
  Checking whether contributing is worth your time must not itself be a
  disclosure, and this is the check that keeps it that way;
- a file from a regime a project has never covered still matches it on every
  input, and reports a domain fraction of 0. Both halves matter: if it stopped
  matching, the platform would hide exactly the contributions that extend a
  model's validity domain;
- `γ (°)` and `rβ (µm)` match through the *discovery* path too, not only on
  upload — they are the literal headings of the source study, so this is the
  case that decides whether a real file finds anything;
- a heading no registry quantity claims is reported rather than dropped, which
  is how a user finds out the registry is missing a quantity;
- unlisted projects appear in neither faceted search nor file matching.

**They write to the database they run against.** Accounts and projects are
tagged with a random suffix so repeated runs do not collide, but they
accumulate. (`smoke_lot0.py` used to be the exception, with one hardcoded
address that made it single-use per database; it is tagged now, and the whole
suite can be run twice in a row.) Run them against a development instance, and reset it when the
clutter bothers you:

```bash
docker compose down -v && docker compose up -d --build
```

## Still to write

One invariant cannot be tested until the code it guards exists: switching a
contribution from federated to shared must not double-count its data
(ARCHITECTURE.md §5.5, lot 5b). The arithmetic underneath it — that `subtract`
exactly undoes `add` — is already checked, so what remains is the end-to-end
path once federated contributions can actually be made.
