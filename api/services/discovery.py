"""Finding a project worth contributing to.

Two ways in, and the second is the one that matters (ARCHITECTURE.md §7).

**Facets** filter on what a project *is*: material, process, the quantity it
predicts, the quantities it consumes, how much data it holds.

**"Match my file"** works the other way round. You drop your CSV before
searching anything, and projects are ranked by how well your columns fit them.
That is the honest direction of the question — a researcher does not know which
projects exist, they know what they measured.

Two rules run through all of this:

* **Never a boolean.** A match is reported as its parts — how many inputs were
  matched, how many of those only approximately, what is missing, and what
  fraction of the rows land inside the project's covered domain. "4/4 inputs,
  one by approximate match — please check" is honest; a green tick is not. A
  column matched to the wrong quantity fits a model to the wrong thing and
  nothing looks broken afterwards.
* **The file is never stored.** Matching parses it in memory and keeps nothing.
  Deciding whether to hand over unpublished measurements should not require
  handing them over first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from api.models import (
    Contribution,
    ContributionStatus,
    ModelVersion,
    Project,
    ProjectInput,
    ProjectStatus,
    ProjectTarget,
    ProjectVisibility,
    Variable,
)
from api.services import coverage
from api.services.matching import match_column
from api.services.tabular import ParsedTable

#: Rows read when working out how much of a file falls inside a project's
#: domain. A fraction estimated on two thousand rows is not improved by reading
#: a hundred thousand, and this endpoint is open to anonymous callers.
MAX_ROWS_SCANNED = 2000

#: Backstop on how many projects are scored against one file. Candidates are
#: already narrowed in SQL to those declaring at least one of the file's
#: quantities, so this only bites on an implausibly large platform — but an
#: unbounded scan behind an endpoint open to anonymous callers is not something
#: to leave lying around. The ordering below it is deterministic on purpose: a
#: LIMIT without an ORDER BY drops arbitrary rows, so the same file could rank
#: differently on two consecutive calls.
MAX_CANDIDATES = 500


# --------------------------------------------------------------------------- #
# Facets
# --------------------------------------------------------------------------- #
def _public() -> Select:
    return select(Project).where(Project.visibility == ProjectVisibility.PUBLIC)


def facets(db: Session) -> dict[str, Any]:
    """The filter values that actually exist, with counts.

    Built from the data rather than hardcoded, so a facet never offers a choice
    that returns nothing — an empty result from a filter the interface itself
    suggested reads as a broken search.
    """
    public = Project.visibility == ProjectVisibility.PUBLIC

    materials = db.execute(
        select(Project.material, func.count(Project.id))
        .where(public, Project.material.isnot(None))
        .group_by(Project.material)
        .order_by(func.count(Project.id).desc(), Project.material)
    ).all()
    processes = db.execute(
        select(Project.process, func.count(Project.id))
        .where(public, Project.process.isnot(None))
        .group_by(Project.process)
        .order_by(func.count(Project.id).desc(), Project.process)
    ).all()

    def variable_counts(link) -> list[dict]:
        rows = db.execute(
            select(
                Variable.key, Variable.display_name, Variable.symbol,
                Variable.unit, func.count(func.distinct(link.project_id)),
            )
            .join(Variable, Variable.id == link.variable_id)
            .join(Project, Project.id == link.project_id)
            .where(public)
            .group_by(Variable.key, Variable.display_name, Variable.symbol, Variable.unit)
            .order_by(func.count(func.distinct(link.project_id)).desc(), Variable.key)
        ).all()
        return [
            {
                "key": key, "display_name": name, "symbol": symbol,
                "unit": unit, "count": count,
            }
            for key, name, symbol, unit, count in rows
        ]

    return {
        "materials": [{"value": value, "count": count} for value, count in materials],
        "processes": [{"value": value, "count": count} for value, count in processes],
        "targets": variable_counts(ProjectTarget),
        "inputs": variable_counts(ProjectInput),
    }


# --------------------------------------------------------------------------- #
# Faceted search
# --------------------------------------------------------------------------- #
def search(
    db: Session,
    *,
    q: str | None = None,
    materials: list[str] | None = None,
    processes: list[str] | None = None,
    inputs: list[str] | None = None,
    targets: list[str] | None = None,
    min_rows: int | None = None,
    has_model: bool | None = None,
    sort: str = "recent",
    limit: int = 50,
) -> list[Project]:
    """Filter public projects.

    Within a facet the choices are alternatives; across facets they accumulate.
    **Inputs are the exception and are required together**, because the question
    a researcher is asking there is "which projects can use the columns I have",
    and a project missing one of their quantities cannot.
    """
    stmt = _public().options(selectinload(Project.owner))

    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Project.title.ilike(like)
            | Project.material.ilike(like)
            | Project.process.ilike(like)
            | Project.description.ilike(like)
        )
    if materials:
        stmt = stmt.where(func.lower(Project.material).in_([m.lower() for m in materials]))
    if processes:
        stmt = stmt.where(func.lower(Project.process).in_([p.lower() for p in processes]))

    for key in targets or []:
        stmt = stmt.where(
            Project.id.in_(
                select(ProjectTarget.project_id)
                .join(Variable, Variable.id == ProjectTarget.variable_id)
                .where(Variable.key == key)
            )
        )
    for key in inputs or []:
        stmt = stmt.where(
            Project.id.in_(
                select(ProjectInput.project_id)
                .join(Variable, Variable.id == ProjectInput.variable_id)
                .where(Variable.key == key)
            )
        )

    if min_rows:
        # Accepted rows only — the same number the project advertises. A draft
        # padded with pending submissions must not answer a size filter.
        stmt = stmt.where(
            Project.id.in_(
                select(Contribution.project_id)
                .where(Contribution.status == ContributionStatus.ACCEPTED)
                .group_by(Contribution.project_id)
                .having(func.coalesce(func.sum(Contribution.n_rows), 0) >= min_rows)
            )
        )
    if has_model is not None:
        published = select(ModelVersion.project_id)
        stmt = (
            stmt.where(Project.id.in_(published))
            if has_model
            else stmt.where(Project.id.notin_(published))
        )

    if sort == "rows":
        # A project nobody has contributed to yet still has to appear, hence the
        # outer join and the coalesce rather than a plain join.
        totals = (
            select(
                Contribution.project_id.label("pid"),
                func.coalesce(func.sum(Contribution.n_rows), 0).label("total"),
            )
            .where(Contribution.status == ContributionStatus.ACCEPTED)
            .group_by(Contribution.project_id)
            .subquery()
        )
        stmt = stmt.outerjoin(totals, totals.c.pid == Project.id).order_by(
            func.coalesce(totals.c.total, 0).desc(), Project.created_at.desc()
        )
    else:
        stmt = stmt.order_by(Project.created_at.desc())

    return list(db.scalars(stmt.limit(limit)))


# --------------------------------------------------------------------------- #
# Match my file
# --------------------------------------------------------------------------- #
@dataclass
class DetectedColumn:
    variable_key: str
    column: str
    confidence: float
    exact: bool
    unit_conflict: str | None = None
    values: list[float] = field(default_factory=list)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def detect_columns(table: ParsedTable, registry: list[Variable]) -> list[DetectedColumn]:
    """Work out which registry quantity each column of a file is.

    Greedy over confidence, and a variable is claimed only once: two headings
    can both look plausible against the same quantity, and letting both win
    would report a file as matching a project twice over on the strength of one
    real column.
    """
    scored: list[tuple[float, str, Variable, bool, str | None]] = []
    for column in table.columns:
        for match in match_column(column, registry):
            scored.append(
                (match.confidence, column, match.variable, match.exact, match.unit_conflict)
            )
    scored.sort(key=lambda item: item[0], reverse=True)

    taken_columns: set[str] = set()
    taken_variables: set[str] = set()
    detected: list[DetectedColumn] = []
    for confidence, column, variable, exact, conflict in scored:
        if column in taken_columns or variable.key in taken_variables:
            continue
        taken_columns.add(column)
        taken_variables.add(variable.key)
        values = [
            number
            for row in table.rows[:MAX_ROWS_SCANNED]
            if (number := _finite(row.get(column))) is not None
        ]
        detected.append(
            DetectedColumn(variable.key, column, round(confidence, 3), exact, conflict, values)
        )
    return detected


def _domain_fraction(
    detected: dict[str, DetectedColumn],
    matched_keys: list[str],
    covered: dict[str, list[float]],
) -> tuple[int | None, int]:
    """How many rows sit inside the project's covered domain, on every matched
    input at once.

    Measured against the range the project has **data** for, never against the
    range it declares. The declared range is a claim; only the covered one says
    where the model can be believed — and a low fraction here is not a reason to
    stay away. It is the sign of a contribution that would extend the domain,
    which is the most valuable kind there is. The interface has to say so.
    """
    usable = [key for key in matched_keys if key in covered and detected[key].values]
    if not usable:
        return None, 0

    rows = min(len(detected[key].values) for key in usable)
    inside = 0
    for index in range(rows):
        if all(
            covered[key][0] <= detected[key].values[index] <= covered[key][1]
            for key in usable
        ):
            inside += 1
    return inside, rows


def match_projects(
    db: Session, table: ParsedTable, registry: list[Variable], *, limit: int = 25
) -> tuple[list[DetectedColumn], list[dict[str, Any]]]:
    """Rank public projects by how well an uploaded file fits them."""
    detected_list = detect_columns(table, registry)
    detected = {item.variable_key: item for item in detected_list}
    if not detected:
        return detected_list, []

    # Narrowed in SQL to projects that actually use one of the file's
    # quantities. A project sharing nothing with the file scores zero and is
    # dropped below anyway, so loading it is pure cost — and on a platform with
    # many projects it is the difference between scoring a handful and scoring
    # all of them.
    relevant = (
        select(ProjectInput.project_id)
        .join(Variable, Variable.id == ProjectInput.variable_id)
        .where(Variable.key.in_(list(detected)))
    )
    projects = list(
        db.scalars(
            _public()
            .where(Project.status != ProjectStatus.ARCHIVED, Project.id.in_(relevant))
            .options(
                selectinload(Project.owner),
                selectinload(Project.inputs).selectinload(ProjectInput.variable),
                selectinload(Project.targets).selectinload(ProjectTarget.variable),
            )
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(MAX_CANDIDATES)
        )
    )
    covered_by_project = coverage.observed_ranges_bulk(db, [p.id for p in projects])

    results: list[dict[str, Any]] = []
    for project in projects:
        inputs = sorted(project.inputs, key=lambda item: item.position)
        input_keys = [item.variable.key for item in inputs]
        target_keys = [item.variable.key for item in project.targets]

        matched_inputs = [key for key in input_keys if key in detected]
        if not matched_inputs:
            continue
        matched_targets = [key for key in target_keys if key in detected]

        missing_required = [
            item.variable.key
            for item in inputs
            if item.required and item.variable.key not in detected
        ]
        approximate = [key for key in matched_inputs if not detected[key].exact]
        conflicts = [
            f"{key}: {detected[key].unit_conflict}"
            for key in matched_inputs + matched_targets
            if detected[key].unit_conflict
        ]

        inside, scanned = _domain_fraction(
            detected, matched_inputs, covered_by_project.get(project.id, {})
        )
        fraction = None if inside is None or scanned == 0 else inside / scanned

        # Weighted rather than lexicographic so that a near-complete match on a
        # big project can outrank an exact one on a project holding nothing.
        # The weights are a judgement, so the parts are reported alongside and
        # the interface shows them: the number orders the list, the parts are
        # what a reader should actually decide on.
        input_cover = len(matched_inputs) / len(input_keys) if input_keys else 0.0
        target_cover = len(matched_targets) / len(target_keys) if target_keys else 0.0
        score = 0.65 * input_cover + 0.20 * target_cover
        weight = 0.85
        if fraction is not None:
            score += 0.15 * fraction
            weight = 1.0

        results.append(
            {
                "project": project,
                "inputs_total": len(input_keys),
                "inputs_matched": len(matched_inputs),
                "inputs_approximate": len(approximate),
                "matched_inputs": matched_inputs,
                "missing_inputs": [key for key in input_keys if key not in detected],
                "missing_required_inputs": missing_required,
                "targets_total": len(target_keys),
                "matched_targets": matched_targets,
                "rows_in_domain": inside,
                "rows_scanned": scanned,
                "fraction_in_domain": fraction,
                "unit_conflicts": conflicts,
                "score": round(score / weight, 4),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return detected_list, results[:limit]
