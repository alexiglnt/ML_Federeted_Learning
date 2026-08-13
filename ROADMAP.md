# Roadmap and handover

**Status: under construction, not deployed, not ready for public use.**

This file is the handover document. It says what exists, what does not, and
what must happen before anyone puts this online. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first for how the pieces fit and why.

Context for whoever picks this up: the rebuild was done in a two-week window
ending late August 2026, with the explicit expectation that it would not be
finished. The work was sequenced so that **every completed lot leaves a site
that runs**. A lot marked incomplete below is genuinely untouched — there are
no half-built features hiding in the tree.

The lots were not done in numerical order. **Lot 5 was built before lot 4**,
deliberately: lot 3 had just shipped prediction, export and the access log
behind a permission that, without owner review, no contributor could ever
obtain. The loop the whole platform runs on — share data, get the model — was a
dead end at `pending`, and discovery would have been an entrance ramp onto a
road that stopped. Lot 4 followed once the road went somewhere.

**Everything through lot 5 is built.** What is left is lot 5b (federated
contributions, whose algebra already exists in `legacy/`) and the blockers
below, which are not features.

---

## Build status

| Lot | Scope | Status |
|---|---|---|
| 0 | Foundations — DB, auth, API and front skeletons, seed data | ✅ done |
| 1 | Variable registry, project creation wizard | ✅ done |
| 2a | Upload, file reading, column mapping, validation | ✅ done |
| 2b | Training service, the two model tracks, versioning, lineage | ✅ done |
| 3 | Project page — validity domain, contributors, prediction, export, settings | ✅ done |
| 4 | Discovery — faceted search and "match my file" | ✅ done |
| 5 | Contribution flow, owner review, retrain, access grant | ✅ done |
| 5b | Federated contribution mode | ✅ done |
| 6 | Handover docs and invariant tests | 🔨 continuous |

Lot 5b was planned as the first casualty if time ran out — not an oversight but
a judgement that **the federated code already existed and worked**, and needed
re-plumbing rather than reinventing. Time did not run out, and it is built. The
pre-rebuild site is still kept whole in [`legacy/`](legacy/) rather than left to
git archaeology: `legacy/web/js/linalg.js` and `score.js` are where the
browser-side algebra came from, and `legacy/README.md` explains the original
federated design in detail.

**Every lot in this plan is now built.** What stands between the current state
and a public deployment is the blockers below, which are legal, institutional
and operational rather than features.

---

## Running it

```bash
docker compose up --build
```

That is the whole contract. No local Node, no local Python — the front end is
compiled inside the Dockerfile on purpose (ARCHITECTURE.md §2.1). Dependency
versions are pinned and lockfiles are committed so a cold restart months later
still builds.

---

## Before this can go online

These are blockers, not polish.

### Legal and institutional

Deliberately deferred during the build. Ordered by risk and by lead time:

1. **Export control (ITAR / EAR) — talk to UNC Charlotte's Export Control
   Officer first.** Machining process data for Ti-6Al-4V and comparable
   aerospace alloys can be controlled technical data. A site with open
   worldwide registration that redistributes it may constitute a deemed export.
   The "fundamental research" exclusion covers university work intended for
   publication, but it protects a platform hosting *third-party industrial*
   data poorly — especially where a contributor marks their data confidential.
   The likely outcome is mild (geo-blocking sanctioned countries, a declaration
   at signup, restrictions on some projects) but the review has the longest
   lead time of anything on this list, so start it first.
2. **Privacy / GDPR.** The measurements are not personal data, but the *user
   accounts* are — and European researchers are an explicit target audience, so
   Art. 3(2) applies extraterritorially. Needed: a privacy policy, working
   account and contribution deletion, and a lawful basis for the EU→US
   transfer. US universities are generally not Data Privacy Framework
   certified; explicit informed consent at signup is the pragmatic route.
3. **Data ownership and citation.** Proposal on the table: the contributor
   retains ownership and grants (a) the platform a storage and processing
   licence, (b) the project owner a research-use licence. Plus a per-
   contribution licence choice and a written citation rule. Settle this
   **before the first real upload**, not after — it is far harder to reopen.
4. Third-party confidential data uploaded without the right to; UNCC IT
   governance approval for a public-facing service; Section 508 / WCAG 2.1 AA
   expectations for a US public university site.

### Technical

- **Email verification at signup is not implemented.** It was skipped to avoid
  a dependency on UNCC SMTP during the build. Open registration without it is
  not acceptable in production.
- **Upload attack surface**, partly hardened. Done: the size cap is enforced by
  reading one byte past the limit rather than trusting `Content-Length`, which
  the client controls; stored filenames are random so a path cannot be derived
  from a user-supplied name; files live in a volume outside anything the web
  server serves; `absolute_path` re-checks that a stored path has not escaped
  the data directory, because a database row is not a trusted input either.
  **Still open: zip bombs inside `.xlsx`** — a small workbook can decompress to
  gigabytes and openpyxl will try.
- Rate limiting, and a review of what the API leaks to unauthenticated callers.
- Backups for the Postgres volume and the uploaded-file store.
- **Staged uploads are never swept.** A file that is uploaded but whose mapping
  is never confirmed stays in `var/data/uploads/staging/` forever. The claim
  token expires after two hours, so the file becomes unreachable but not gone.
  A periodic sweep of files older than the token lifetime is a few lines and is
  not written yet.
- **CSV formula injection is handled on the way out; `.xlsx` is not.** Lot 3
  opened the hole and closed most of it: the owner can now download a
  contributor's file, and `storage.sanitise_csv` prefixes a quote onto any cell
  that leads with `=`, `+`, `-` or `@` *and* is not a number — the number test
  matters, because a residual stress of `-454.0` is exactly the kind of value
  this platform carries and naive escaping would corrupt every one of them.
  Covered by `tests/smoke_lot3.py` from both directions. **What remains: an
  uploaded `.xlsx` is served back byte for byte**, so a formula in a spreadsheet
  cell still reaches whoever opens it. The download forces a save and sends
  `nosniff`, which is not the same as being safe. Either rewrite the workbook
  on the way out or convert it to sanitised CSV.

---

## What lot 0 actually delivers

The full schema of ARCHITECTURE.md §6 is migrated — including the tables for
features not yet built, so adding them later is not a migration against a live
database. On top of that: session authentication, the variable registry with
column matching, the React shell, and a seed that fills an empty database with
14 machining quantities and a demo project drawn from the Outeiro study.

Verified end to end from empty volumes: `docker compose down -v` followed by
`docker compose up --build` produces a working site. Column headings written
`γ (°)` and `rβ (µm)` match the registry correctly, which is the case that
matters because they are the literal headings in the source study.

Pages that exist but say "not built yet" do so deliberately — the navigation is
honest about the build state rather than offering dead links.

## What lot 1 adds

Projects can be created and read. The creation form picks inputs and targets
from the registry, lets a missing quantity be proposed inline and used at once,
and stores input order — which is contractual, not cosmetic, because a
contribution whose columns are permuted fits silently wrong coefficients.

Rules enforced and covered by the smoke test: a variable cannot be both input
and target of one project (it would predict a column from itself); duplicates
are rejected; slugs are unique and permanent, suffixed on collision rather than
reused; a *proposed* registry variable is usable by its proposer immediately
but by nobody else until moderated; the permission matrix holds for anonymous
visitors, other signed-in users, and the owner.

New projects start as `draft` — they have no data, so there is nothing to
contribute to yet. Lot 2 is what promotes them.

## What lot 2a adds

Files can be uploaded, read and committed. `api/services/tabular.py` is the
Python port of the original site's CSV heuristics, plus `.xlsx` — which the
browser-only version could not do, and which is what most people actually have.
It handles semicolon separators, decimal commas, title rows above the header,
Greek letters and units in column names, and several text encodings.

Uploading is **two steps on purpose**: the file is parsed and set aside, the
user confirms the column mapping, and only then is anything recorded. A file
read with the wrong decimal mark parses without complaint, so the preview table
exists to make that visible rather than discoverable months later. Column
suggestions carry a confidence and are always confirmed — a column matched to
the wrong quantity fits the model to the wrong thing and nothing looks broken
afterwards.

Enforced and covered by `tests/smoke_lot2a.py`: required inputs must be mapped;
at least one target must be; one column cannot serve two quantities; the
`MIN_ROWS` privacy floor holds; an identical file cannot be submitted twice to
one project (it would weigh twice in the fit); a staged upload cannot be
claimed by another user; the owner's own data is auto-accepted while anyone
else's lands `pending`; and pending data neither inflates the row count nor
widens the published validity domain.

Data **outside** a project's declared range warns and never blocks. That is
load-bearing: measurements from an uncovered regime are the most valuable
contribution there is, because they extend the model's domain.

## What lot 2b adds

Projects train. Committing accepted data queues a background retrain, and each
run publishes a version with its lineage — which contributions went in, and
what the scores did.

Every version fits **both tracks** (ARCHITECTURE.md §5.4): the owner's chosen
engine on shared rows, and a linear-family reference model that federated
contributions can also feed. Six engines are available; `linear`, `ridge` and
`piml` publish an equation, `gpr`, `gbm` and `rf` store an estimator instead.
Lambda and alpha are selected by cross-validation rather than assumed, and the
sweep is published so a reader can see how sharp the choice was.

Every version is a **full refit from the accepted data**, never an incremental
update. That is what the platform buys by holding the raw files: dropping a bad
contribution, or deleting one on request, is "retrain without it" rather than an
attempt to unpick its influence.

**Metrics are public, the model is not** — that split is the incentive the
platform runs on, and it is tested for anonymous visitors, signed-in
non-contributors and the owner.

Scores are reported in the order they deserve. Leave-one-lab-out leads,
cross-validated R² follows, and training R² is shown last with a note that it
is not a measure of performance — five parameters on seven points look
excellent whatever the data says. Leave-one-lab-out groups by **contributor**,
not by file: one lab submitting two datasets is still one lab, and grouping by
file would validate a model against data from the very lab it was trained on.
`tests/check_engines.py` shows it earning its place — a lab with a systematic
offset scores 0.17 against 0.63 for ordinary cross-validation, while labs that
agree give 0.997 against 0.997.

`_reference_statistics` merges federated sufficient statistics into the
reference fit. Nothing produced them until lot 5b; there is now an end-to-end
path and `tests/smoke_lot5b.py` walks it, alongside the arithmetic check in
`tests/check_aggregation.py`.

## What lot 3 adds

The project page now answers the questions a visitor actually arrives with, in
that order: what is this about, **where can it be believed**, how good is it,
what made it move, and who made it.

The validity-domain bar per input is the part worth understanding. It draws
three things on one axis — the range the owner *declared*, the range the
owner's own data *covers*, and how far contributions pushed that. They are
routinely different, and only the last two license belief in a prediction. The
prediction endpoint warns against the covered range for the same reason, never
against the declared one; `tests/smoke_lot3.py` pins that distinction by
declaring a maximum of 75, holding data only to 60, and asserting the warning
quotes 60.

Also built, all of it gated by the matrix in ARCHITECTURE.md §4.1 rather than
by anything the front end decides for itself:

- a **public contributor list** — the credit is public, the file is not, and a
  pending contribution is not listed at all because the owner has not agreed to
  it yet;
- a **prediction page** for anyone who has earned model access, which prefills
  each input at the middle of the covered range rather than at zero, hints
  while typing when a value leaves that range, and puts the extrapolation
  warning *above* the numbers instead of below them;
- a **model export** — one citable JSON document carrying units, metrics,
  licence and the exact contributions behind the fit, so a reader of a paper
  can tell what the numbers were fitted on;
- an **owner settings screen** covering everything that does not change the
  meaning of data already stored. Inputs and targets are absent by design and
  the page says why: altering them would leave every column mapping already
  recorded against the project quietly wrong;
- **raw-file download** for the owner and for the contributor themselves, with
  the **access log shown to contributors**, not just to the owner. That is the
  counterpart of asking researchers to hand over unpublished measurements, and
  downloads made through the page refresh the log underneath it.

The gate is tested from both sides: a *pending* contributor is refused
prediction, export and everyone else's files. Lot 5 is what lets anyone through
it — until that was built, the owner was the only account on a project that
could predict or export at all.

One thing the front end deliberately does not do is re-derive who may see
what. `viewer_can_use_model` and `viewer_can_read_raw_data` come down on the
project, so the interface cannot drift into a subtly more generous reading of
the permission matrix than the API enforces.

## What lot 4 adds

Discovery, both directions (`api/services/discovery.py`).

**Facets** filter on what a project is — material, process, the quantity it
predicts, the quantities it consumes, how much accepted data it holds, whether
it has a trained model. The values are built from the data with counts, so a
facet never offers a choice that returns nothing. Within a facet the choices are
alternatives; across facets they accumulate. **Inputs are the exception and
accumulate too**: the question behind that filter is "which projects can use the
columns I have", and a project missing one of those quantities cannot.

**"Match my file"** is the half that matters and it is placed above the filters
on the page. A researcher arriving does not know which projects exist — they
know what they measured — so they drop the file first and projects are ranked
against it. Two properties are load-bearing:

- **Never a boolean.** Every part is reported: inputs matched out of total, how
  many only by approximate name match, what is missing, which targets are
  present, unit conflicts, and what fraction of the rows fall inside the range
  the project has *data* for. The single `score` exists to order the list and
  is a weighted judgement, so the parts sit beside it and the card shows them.
- **A low domain fraction is an opportunity, not a warning.** Data from a regime
  a project has not covered is the most valuable contribution there is, and the
  card says so in those words. Presented as a failure it would drive away
  exactly the data the platform most needs.

**Nothing is stored.** The file is parsed in memory and discarded with the
response — no staging, no row, no audit entry — and the page says so. Deciding
whether to hand over unpublished measurements should not require handing them
over first. The smoke test asserts it from the outside: after matching, the
project's row count, contribution list and version list are all untouched.

Two things found while testing rather than while writing, both now fixed:

- the candidate query had a `LIMIT` with no `ORDER BY`, so on a platform with
  more projects than the cap it would silently score an arbitrary subset and the
  same file could rank differently on two consecutive calls. Candidates are now
  narrowed in SQL to projects declaring at least one of the file's quantities,
  and ordered before the cap applies;
- the match endpoint takes a `limit`. Structurally identical projects tie at the
  top of the ranking, and a partial match can sit below the first page — which
  is correct ranking but made the result depend on how much else was in the
  database.

## What lot 5 adds

The loop closes. A contribution can be accepted, and accepting it is what
grants model access — so the exchange the platform is built on now actually
happens, and `tests/smoke_lot5.py` walks it end to end: another lab uploads,
the owner accepts, and that lab can predict and export where a moment earlier
it was refused.

**The two scores of §5.3 are computed on arrival** (`api/services/scoring.py`).
Transfer applies the published model to the new rows unchanged; refit fits the
contributor's rows on their own and cross-validates them. The transfer score
records the version it was measured against, because a score against "the
model" means nothing once the model has moved. The refit deliberately uses the
linear reference engine and not the project's main engine: the question is
whether the measurements are self-consistent, and a Gaussian process on seven
points answers that flatteringly whatever the data says.

The review card states the **reading** next to the numbers rather than leaving
it in a document nobody has open, because one of the four cases is a trap.
Transfer poor with refit good is not a bad contribution — it is clean data from
a regime the model does not cover, which is the most valuable thing this
platform can receive, and an owner who reads the transfer score as a verdict
throws away precisely what they should be keeping. The smoke test constructs
that case on purpose (a high-speed regime, exactly linear) and asserts the two
scores diverge the way §5.3 says they will.

**Everything is reversible, and access follows the data.** The owner can reject
something already accepted; the contributor can withdraw. Both revoke model
access unless that person still has other accepted data here, and both queue a
retrain — because otherwise a contributor could unlock a model and then pull
their data back out, which is the free ride review exists to prevent. Rejecting
something merely *pending* queues nothing, since pending data was never in a
model. What the owner cannot do is reinstate what a contributor withdrew.

ARCHITECTURE.md §8.4 — a rejected or withdrawn contribution leaves no trace in
the next trained version — holds by construction, because every version is a
full refit from the accepted set rather than an incremental update. It is
asserted directly against the version lineage rather than taken on trust.

Two things worth knowing about the shape of this:

- `api/services/inference.py` is new and is now the **only** place a stored
  model turns back into predictions. The prediction endpoint and the transfer
  score both go through it, so the rule that coefficients are looked up by
  variable key and never by position exists once rather than in two copies that
  can drift.
- `revoke_contributor_access_if_unearned` requires its caller to have flushed
  the status change first. Sessions are created with `autoflush=False`, and an
  unflushed change is invisible to the query it makes — it concludes the access
  is still earned and leaves it in place while reporting a revocation. This was
  a real bug during the build, caught by the smoke test rather than by reading,
  and the docstring now says so.

## What lot 5b adds

The mode the original site was built around: contributing without handing over
the data. The file is read **in the contributor's browser**
(`web/src/lib/federated.ts`) and only `n`, `D'D`, `D'y` and `y'y` per target are
transmitted. No measurement passes through `lib/api.ts`.

The claim this rests on is now checked end to end rather than only in the
abstract. `tests/smoke_lot5b.py` builds two projects from identical
measurements — one receiving half as a file and half as sums, the other
receiving all twenty rows as one file — and compares their published
coefficients: **3e-11 apart on a scale of 600**. That is the §5.1 claim
surviving HTTP, JSONB and a background retrain, not just the arithmetic.

Three things worth knowing about how it is built:

- **The sums are checked, not trusted.** The client computes them and the server
  cannot see the data behind them, so `api/services/federated.py` verifies what
  must be true of any real dataset: `D'D` symmetric and positive semi-definite,
  `D'D[0,0]` equal to the row count, the three sums mutually consistent (they
  must not imply a negative residual sum of squares), and the declared input
  ranges compatible with the means and variances the sums encode. A fabricated
  validity range is caught by Popoviciu's inequality. Every one of these has a
  test that submits a doctored summary and expects a refusal.
- **The scores are recomputed server-side.** §5.3 notes that `SSE(theta)` is
  expressible in the sums, so the transfer score is derived rather than
  accepted — a contributor cannot flatter their own submission. The refit score
  is honestly weaker here and says so in the payload: fitting on the sums is
  exact, but cross-validating is not possible, because leave-one-out removes
  points one at a time and summed statistics cannot. It reports a *training*
  score and labels it as one.
- **The double-counting trap is closed by construction, not by discipline.**
  ARCHITECTURE.md §5.5 warns that a federated contributor who later shares their
  file must remain one row whose mode changes. So the ordinary upload endpoint
  **refuses** a file from someone who already has a federated contribution here,
  and names the conversion route instead; `.../contributions/{id}/share` deletes
  the summaries as it attaches the dataset. The test asserts the outcome that
  matters: after converting, the project holds twenty rows, not thirty, and the
  coefficients still match the pooled fit exactly.

The incentive survives intact and is tested from both sides: an accepted
federated contribution is credited publicly, widens the published validity
domain, appears in the version lineage and feeds the reference model — and
grants **no** model access. Sharing the file later does, immediately.

One deliberate limit: federated mode accepts CSV and tab-separated text, not
`.xlsx`. Unpacking a spreadsheet in the browser needs a library, and this page
loads no third-party code on purpose — that is what lets a contributor read it
and satisfy themselves nothing leaves. The page says so and offers the shared
path instead, where the server does the reading.

## Known gaps and deliberate omissions

- Categorical inputs exist in the schema but only continuous variables are
  implemented. ARCHITECTURE.md §6.1 explains the trap to avoid when adding
  them — the category set must be frozen per project or federated sums stop
  being addable.
- `project_inputs.penalised_sign` carries **one** PIML physical prior per
  input, applied to all of a project's targets. The prior is really a claim
  about an (input, target) pair; sharing it across targets is the same
  simplification the original single-model site made, and it holds only while
  a project's targets are physically alike. A project predicting two quantities
  that respond oppositely to the same input needs this per target.
- **No notification system.** An owner learns of a pending contribution only by
  visiting the project page, and a contributor learns of a decision the same
  way. Now that review is the step everything else waits on, this is the most
  keenly felt gap in the build: a contribution can sit unseen indefinitely, and
  the contributor has no way to tell whether it was ignored or rejected. The
  review queue is put at the top of the project page to soften that, which is a
  workaround and not a fix.
- **Rejecting the last accepted contribution leaves the published model
  standing.** Retraining is queued, but it fails with "not enough accepted
  data" and there is no path that un-publishes an existing version. The model on
  the page then still contains data nobody has accepted any more. The training
  job records the failure and the owner sees it, so this is visible rather than
  silent, but the honest fix is for a project with no accepted data to stop
  publishing a model at all.
- No project transfer or co-ownership, so an abandoned project has no path to a
  new maintainer.
- **Discovery is not paginated and its listings are N+1.** Both the faceted list
  and the match results build a summary per project with two queries each, and
  neither offers a second page — the faceted list caps at 200 projects and
  matching scores at most 500 candidates. Fine for a platform holding tens of
  projects, which is the realistic size for years; wrong before it holds
  thousands. The match ranking also ties readily, since any two projects whose
  inputs a file fully covers score identically, and nothing breaks those ties.
- Unit conversion between a project's unit and the registry's canonical unit is
  specified but verify it is implemented on every path before trusting it.

---

## Where to start reading the code

1. `ARCHITECTURE.md` §5 — the mathematics. It is the only genuinely subtle part
   of the codebase, and the two warnings in §5.4 and §5.5 describe failures
   that are silent rather than loud.
2. The SQLAlchemy models — the data model is the spine of everything.
3. The training service — where the two model tracks are actually fitted.
4. `api/routers/uploads.py`, function `_settle` — the three consequences of a
   review decision (access, the model, the record) and why they have to move
   together. It is short, and it is where the platform's incentive is actually
   implemented rather than described.

The pre-rebuild history is worth a look for the original single-model site: it
is small, well commented, and its README explains the federated design in
detail. Its comments were in French and were translated during the port.
