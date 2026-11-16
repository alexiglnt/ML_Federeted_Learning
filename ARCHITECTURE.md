# Architecture

This document is the reference for how the platform is put together and, more
importantly, **why**. It is written for someone arriving cold, months from now,
with no access to the people who built it.

Read [ROADMAP.md](ROADMAP.md) next: it says what is built, what is not, and
what has to happen before this can go online.

---

## 1. What this is

A platform for pooling machining measurements.

The problem it addresses is scarcity. A researcher measuring residual stress on
Ti-6Al-4V may have **seven** conditions — that is what the Outeiro 2022 study
has, and it is typical. Each measurement costs time, money and machine access.
No single lab can gather enough data to fit a model that generalises.

So: anyone can create a **project** by declaring the input variables they
measure and the quantity they predict. They upload their own data and get a
model. Other researchers who measure the same variables can find that project
and contribute their data to improve it — and in exchange, get access to the
resulting model.

### 1.1 Where this came from

The repository began as something narrower: a single hardcoded model
(Ti-6Al-4V, four inputs, two residual-stress targets) with a strong privacy
guarantee — the fitting ran **in the contributor's browser**, and only summary
statistics were transmitted. Measurements never left the contributor's machine.

That guarantee is preserved, but it is no longer the only mode. See §4.

The mathematics of the original site survives intact and is the load-bearing
idea of the whole platform. It is explained in §5.

---

## 2. Stack

| Layer | Choice | Note |
|---|---|---|
| Database | PostgreSQL | Users, projects, permissions, faceted search. |
| API | FastAPI + SQLAlchemy + Alembic | Python was already here and the ML lives in Python. |
| Training | scikit-learn, plus the in-house PIML solver | Runs server-side, in background jobs. |
| Front end | React + Vite + TypeScript | |
| Serving | Docker Compose + Caddy | Caddy terminates TLS. |

### 2.1 The one rule about the build

**The front end is compiled inside the Dockerfile.** Nobody needs Node or
Python installed to run this project — `docker compose up` is the entire
contract. Dependency versions are pinned and lockfiles are committed.

This is deliberate and it is not negotiable without a good reason. The realistic
scenario for this codebase is that it sits untouched for months and someone
tries to restart it cold. A React toolchain that must be reconstructed from
unpinned dependencies in 2027 is a codebase that gets abandoned instead of
resumed.

---

## 3. The variable registry

Projects do not name their inputs in free text. They pick them from a
**canonical registry of physical quantities**.

```
key             symbol  unit     kind         penalised_sign
cutting_speed   Vc      m/min    continuous   +1
rake_angle      γ       deg      continuous   -1
edge_radius     rβ      µm       continuous   -1
uncut_thickness h       mm       continuous   +1
feed            f       mm/rev   continuous    —
coolant         —       —        categorical   —
```

This is the single decision that determines whether the platform works or
becomes a graveyard. Under free-text naming, forty projects would declare
`Vc`, `vc`, `cutting speed`, `vitesse de coupe` and `V_c (m/min)`, none of them
matching each other, and **discovery — the core feature — would return
nothing**.

With a registry:

- search by input variable is exact rather than approximate;
- units are known, so a contributor working in mm/min is **converted**, not
  rejected;
- column matching against an uploaded file is reliable, because the registry
  carries the aliases;
- the registry can *suggest* a PIML physical prior (§5.2) when a project adds
  the variable, instead of every owner working it out from scratch.

On that last point, note what the registry does **not** own. The prior is a
claim about an (input, target) pair — "raising cutting speed makes residual
stress less compressive" says nothing about cutting speed by itself — so the
authoritative `penalised_sign` lives on `project_inputs`, and the registry only
pre-fills the form.

**The escape hatch matters as much as the registry.** A user whose quantity is
missing declares a new one — name, unit, dimension — and uses it *immediately*
in their project. It simultaneously enters a moderation queue for promotion
into the shared registry. Without this, the first researcher with an unusual
measurement is turned away, and the registry's completeness becomes a blocker
instead of an asset.

---

## 4. Contribution modes, and who gets what

**The contributor chooses the mode, per contribution.** It is not a project
setting.

| | Federated | Shared |
|---|---|---|
| What is transmitted | summary sums only (§5.1) | the data file |
| Raw data readable by owner | no | **yes** |
| Credited as contributor | yes | yes |
| Extends the published validity domain | yes | yes |
| Feeds the reference model | yes | yes |
| Feeds the main model | **no** | yes |
| **Access to the model** | **no** | **yes** |

Model access is the exact counterpart of sharing data. That is the incentive
gradient the platform runs on.

A federated contributor still gets something real: their own two scores
computed locally (§5.3), attribution, and an improved reference model. The UI
must state plainly what they do and do not receive — and offer the upgrade
path, since a federated contributor can later share their file to unlock
access.

### 4.1 Permissions

| | Project exists, inputs, ranges | Metrics (R², n, versions) | The model (coefficients, prediction) | Raw files |
|---|:---:|:---:|:---:|:---:|
| Anonymous / any user | ✅ | ✅ | ❌ | ❌ |
| Accepted contributor (shared) | ✅ | ✅ | ✅ | ❌ |
| Owner | ✅ | ✅ | ✅ | ✅ (all) |

Metrics being public is deliberate: it is what tells a visitor whether
contributing is worth it. *"47 points across 5 labs, R² 0.81 — contribute to
unlock the model."* Hide the metrics and nobody has a reason to join.

A contributor never sees another contributor's file. Only the owner does.

### 4.2 Contributions require owner review

A contribution lands as `pending`. The owner sees the metadata, the two scores,
and — in shared mode — the data itself, then accepts or rejects. Only on
acceptance does the data enter a model and the contributor gain access.

This exists because *"share data → get the model"* is an open invitation to
upload noise in order to unlock a model. Review is the defence. The original
codebase made the same call for the same reason: an endpoint that silently
alters a global model is poisonable.

---

## 5. The mathematics

This section is the part of the codebase that is genuinely subtle. Everything
else is plumbing.

### 5.1 Sufficient statistics: why federated aggregation is exact

With design matrix `D = [1, X]`, the residual sum of squares is

```
SSE(theta) = y'y − 2 theta'(D'y) + theta'(D'D) theta
```

This depends on the data **only** through `D'D`, `D'y`, `y'y` and `n` — and
those four quantities are **additive across labs**. Summing them and refitting
gives coefficients identical, to numerical precision, to what fitting on the
pooled raw table would have given.

This is not FedAvg. Most federated implementations average client weights,
which is an approximation and a poor one when clients differ wildly in size —
precisely our case, one lab with 7 conditions and another with 40. Here nothing
is averaged; the fit is exact. The original repository verified this to 1e-13.

### 5.2 PIML

A least-squares fit plus a penalty on coefficients whose **sign contradicts
physics**:

```
loss = MSE + lam * sum( max(0, penalised_sign_j * coef_j)^2 )
```

The intercept is never penalised. The loss is convex and piecewise quadratic,
so it is solved exactly by an active-set iteration rather than by a general
optimiser — at a fixed violation set `A`,

```
(D'D + n * lam * P_A) theta = D'y      with  P_A = diag(0, 1_A)
```

solve, recompute `A`, repeat until it stops moving. This replaced L-BFGS-B
because the loss has a very flat valley and L-BFGS stopped at visibly different
points depending on conditioning — up to 2 MPa/mm of disagreement on a
coefficient between two fits that ought to be identical.

Note it also depends on the data only through the sufficient statistics, so
PIML aggregates exactly too.

### 5.3 The two scores

Computed for every incoming contribution, and shown to the owner at review:

| | What is computed | The question it answers |
|---|---|---|
| **Transfer** | the published model applied as-is, no refitting | does our model work outside our own lab? |
| **Refit** | refitted on the contributor's data alone, scored by cross-validation | are these measurements predictable at all? |

Read as a pair:

- transfer good → consistent with existing data, accept;
- transfer poor **but** refit good → clean data from a physical regime the
  model does not cover. **This is the most valuable contribution there is** —
  it extends the validity domain. Do not reject it for a poor transfer score;
- transfer poor **and** refit poor → noise. Flag to the owner.

For a federated contribution the server can **recompute the transfer score
itself** from the sums, since `SSE(theta_global)` is expressible in `D'D`,
`D'y`, `y'y`. A client cannot fake it.

### 5.4 ⚠️ Two model tracks per project — do not remove this

Sufficient statistics reconstruct a **quadratic** loss. That covers ordinary
least squares, ridge, and PIML. It does **not** cover Gaussian processes,
gradient boosting, random forests or symbolic regression — those need the
individual rows, and no summary replaces them.

So a federated contribution to a project whose model is a GPR would be
mathematically unusable. Accepting data that cannot be used is worse than
declining it.

Every project therefore trains **two** models:

| Track | Trained on | Fed by | Engines |
|---|---|---|---|
| **reference** | all pooled data — shared rows *and* federated sums | everyone | linear, ridge, PIML |
| **main** | shared files only | shared contributors | GPR, boosting, RF, PySR, … |

Consequences, all of them good:

- a federated contribution is never wasted;
- the incentive survives — the good model is still fed only by sharers;
- publishing a linear reference alongside a complex model is good practice
  anyway. If the GPR does not beat linear regression, that is a finding, and it
  is the first thing a reviewer asks.

Without two tracks the alternative was to forbid federated contributions on
non-linear projects — at which point owners pick a non-linear engine
deliberately, to force sharing. That door is closed.

### 5.5 ⚠️ The double-counting trap

A federated contributor who later shares their file to unlock model access
would have their data enter the reference model **twice**: once through the
sums, once through the rows. Silently. The model would simply be wrong, with
nothing visibly broken.

Therefore: a `Contribution` is **one row whose mode changes**, never two rows.
Switching federated → shared must subtract the sufficient statistics from the
pool before adding the raw rows. Sums are subtractive, so this is mechanically
easy — it is only easy to *forget*. There is a test for it. Keep it.

### 5.6 Leave-one-lab-out — the metric that justifies the platform

Once a project holds data from several labs, it can compute something no single
lab can: train on labs A, B, C, predict lab D, and rotate.

That is the question a researcher actually has — *does this model work anywhere
other than where it was built?* — and an ordinary cross-validated R² never
answers it, because it holds out points, not sources. This platform is the only
place the measurement is possible. It belongs on the project page, prominently.

### 5.7 Poolability — checked live, never cached

§5.3's two scores answer "is this contribution good on its own terms" —
against the published model (transfer) and against itself (refit). Neither
answers the question that only matters once a project has more than one
contributor: *if this is accepted, does §5.6's leave-one-lab-out score get
better or worse for everyone else too?* A row can be perfectly
self-consistent and still be the outlier that wrecks it for the rest of the
pool. That failure mode is invisible to transfer and refit alike, and it is
the whole subject of a systematic audit this platform grew a feature from:
one bad row pulled a published baseline's honest R² from 0.61 to −4.86.

Two numbers, computed against the *current* accepted pool, for a pending
**shared** contribution only:

- **own score** — a model fit on every accepted contributor except this one,
  scored against this contribution's own rows. Does everyone else's data
  predict this lab?
- **pool effect** — leave-one-lab-out R² of the accepted pool, before vs.
  after adding this contribution as one more group. Does accepting it move
  the model's honest score for everyone, not just for this lab?

Shared-mode only, unlike transfer and refit: a federated contribution never
gives the server raw rows, only `n`, `D'D`, `D'y`, `y'y` (§5.1). A true
held-out check needs an actual row to predict and compare, which does not
exist server-side for a federated contributor. Rather than publish an
approximate number under an honest-sounding name, a federated pending
contribution gets an explanation instead of a score.

And unlike transfer and refit, poolability is **never persisted** on the
`Contribution` row. Transfer is explicitly pinned to a version number — "measured
against v{N}" — because a stale, labelled score is still meaningful history.
Poolability has no such anchor: it is a question about the *current* accepted
pool, and that pool changes underneath a pending contribution every time
another one is accepted or rejected elsewhere. Caching it would go stale
between two reviewers' decisions with nothing visibly wrong. So it is computed
on request, each time, from whatever is accepted right now.

---

## 6. Data model

```
users                 id, email, password_hash, full_name, institution,
                      country, role, created_at

variables             id, key, display_name, symbol, unit, dimension,
                      kind (continuous|categorical), categories,
                      penalised_sign, status (approved|proposed|rejected),
                      proposed_by
variable_aliases      variable_id, alias (normalised form)

projects              id, slug, owner_id, title, description, material,
                      process, visibility, status, main_engine,
                      accepts_federated, licence
project_inputs        project_id, variable_id, position, required, unit,
                      expected_min, expected_max, penalised_sign
project_targets       project_id, variable_id, position, unit

contributions         id, project_id, contributor_id,
                      mode (shared|federated),
                      status (pending|accepted|rejected|withdrawn),
                      n_rows, measurement_method, feature_ranges,
                      transfer_score, refit_score,
                      submitted_at, reviewed_at, reviewed_by, review_note
datasets              contribution_id, original_filename, stored_path,
                      content_hash, column_mapping, parse_report
                      -- shared mode only
federated_stats       contribution_id, target_variable_id, n, dtd, dty, yty
                      -- federated mode only

model_versions        id, project_id, number, created_at, note,
                      n_rows_total, n_contributions
model_version_sources model_version_id, contribution_id      -- the lineage
fitted_models         version_id, track (reference|main), target_variable_id,
                      engine, hyperparams, metrics, coefficients, scaler,
                      equation, artefact_path

project_access        project_id, user_id, role (owner|contributor|viewer),
                      granted_at, source_contribution_id
training_jobs         id, project_id, status, kind, error, log
audit_log             actor_id, action, object_type, object_id, detail, at
```

Notes on shape:

- A **version is a project-level snapshot**, and `fitted_models` hangs off it —
  one row per (track × target). A project with two targets produces four fitted
  models per version, but the UI timeline shows one "v6".
- `model_version_sources` is what makes the version timeline answer *"which
  data made the model move?"* — the feature that was named as the most
  important one on the project page.
- `datasets` and `federated_stats` are mutually exclusive per contribution. See
  §5.5.
- `audit_log` records raw-file downloads. This is worth surfacing **to
  contributors**: it builds trust, and it is the kind of transparency a data
  protection review will ask for.

### 6.1 Categorical inputs

The schema supports them; v1 only implements continuous variables.

The subtlety to preserve: under one-hot encoding, sufficient statistics still
work — **provided the category set is frozen at the project level**. If two
contributors encode their categories in different orders, their sums are no
longer addable and the reference model silently corrupts. Freeze the categories
in `variables.categories`, and encode from that list, never from what happens
to appear in an uploaded file.

---

## 7. Site layout

```
/                       landing — pitch, search, recent projects, counters
/projects               ★ discovery (see below)
/projects/new           creation wizard
/projects/:slug         project page — tabs below
/projects/:slug/contribute
/projects/:slug/predict use the model (access required)
/me                     my projects, contributions, access, notifications
/variables              the public registry
/docs                   file format, methodology, legal
/admin                  platform moderation
```

**Discovery** works two ways. Faceted filtering (target quantity, material,
process, input variables, size) — and, more importantly, **"match my file"**:
you drop your CSV *before* searching, the site reads your columns against the
registry and ranks projects by compatibility, reporting both how many inputs
match and what fraction of your rows fall inside each project's validity
domain. Show a compatibility *score*, never a boolean: "4/4 inputs, 1 by
approximate match — please check" is honest.

**The project page** carries: the input table with a validity-domain bar per
variable (owner's coverage vs. what contributions added), the current model
card, the version timeline with per-version lineage, and the contributor list.
Tabs beyond that are gated by §4.1.

---

## 8. Invariants worth a test

The handful of things that break silently rather than loudly:

1. Aggregating from summed sufficient statistics equals fitting on pooled raw
   data (the original repo checked this to 1e-13 — keep that check).
2. Switching a contribution federated → shared does not double-count (§5.5).
3. The permission matrix in §4.1, especially that a contributor cannot reach
   another contributor's file.
4. A rejected or withdrawn contribution leaves no trace in the next trained
   version.
5. Column mapping is order-sensitive — permuted inputs produce silently wrong
   coefficients. The original server rejected any contribution whose feature
   order disagreed with the model's. Preserve that.
