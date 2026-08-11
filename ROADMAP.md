# Roadmap and handover

**Status: under construction, not deployed, not ready for public use.**

This file is the handover document. It says what exists, what does not, and
what must happen before anyone puts this online. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first for how the pieces fit and why.

Context for whoever picks this up: the rebuild was done in a two-week window
ending late August 2026, with the explicit expectation that it would not be
finished. The work was sequenced so that **every completed lot leaves a site
that runs**. If a lot below is marked incomplete, nothing downstream of it was
started — there are no half-built features hiding in the tree.

---

## Build status

| Lot | Scope | Status |
|---|---|---|
| 0 | Foundations — DB, auth, API and front skeletons, seed data | ✅ done |
| 1 | Variable registry, project creation wizard | ⬜ not started |
| 2 | Upload, column mapping, validation, training, versioning | ⬜ not started |
| 3 | Project page — inputs, validity domain, version timeline | ⬜ not started |
| 4 | Discovery — faceted search and "match my file" | ⬜ not started |
| 5 | Contribution flow, owner review, retrain, access grant | ⬜ not started |
| 5b | Federated contribution mode | ⬜ not started |
| 6 | Handover docs and invariant tests | 🔨 continuous |

Lot 5b is the intended first casualty if time runs out, and that is a
deliberate choice rather than an oversight: **the federated code already exists
and works** — the algebra, the exactness tests, the aggregation logic. It needs
re-plumbing into the new architecture, not reinventing. It is preserved in
[`legacy/`](legacy/), which is the entire pre-rebuild site, kept on disk rather
than left to git archaeology. Start with `legacy/README.md` and
`legacy/server/piml.py`, and see ARCHITECTURE.md §5.

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
- **Upload attack surface** needs hardening: file size caps, CSV formula
  injection on export (`=cmd|…` opening in Excel), zip bombs inside `.xlsx`,
  filename path traversal, storage outside the web root.
- Rate limiting, and a review of what the API leaks to unauthenticated callers.
- Backups for the Postgres volume and the uploaded-file store.

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

Pages that exist but say "not built yet" (projects, dashboard) do so
deliberately — the navigation is honest about the build state rather than
offering dead links.

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
- No notification system; owners must visit the project to see pending
  contributions.
- No project transfer or co-ownership, so an abandoned project has no path to a
  new maintainer.
- Unit conversion between a project's unit and the registry's canonical unit is
  specified but verify it is implemented on every path before trusting it.

---

## Where to start reading the code

1. `ARCHITECTURE.md` §5 — the mathematics. It is the only genuinely subtle part
   of the codebase, and the two warnings in §5.4 and §5.5 describe failures
   that are silent rather than loud.
2. The SQLAlchemy models — the data model is the spine of everything.
3. The training service — where the two model tracks are actually fitted.

The pre-rebuild history is worth a look for the original single-model site: it
is small, well commented, and its README explains the federated design in
detail. Its comments were in French and were translated during the port.
