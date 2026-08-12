"""Where a project's accepted data actually sits.

Kept apart from the routers because two of them need it and neither should
import the other: the project page draws it, and the prediction endpoint uses
it to say when a prediction is an extrapolation.

The distinction that matters throughout: a project's **declared** range is what
the owner said the project is about, and its **covered** range is where there
is data. Only the second one licenses belief in a prediction.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Contribution, ContributionStatus, Project


def _merge(ranges: dict[str, list[float]], entry: dict | None) -> None:
    """Fold one contribution's declared ranges into an accumulating union."""
    for key, bounds in (entry or {}).items():
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            continue
        try:
            low, high = float(bounds[0]), float(bounds[1])
        except (TypeError, ValueError):
            continue
        current = ranges.get(key)
        ranges[key] = (
            [low, high]
            if current is None
            else [min(current[0], low), max(current[1], high)]
        )


def observed_ranges(
    db: Session, project: Project, *, owner_only: bool = False
) -> dict[str, list[float]]:
    """Union of the accepted contributions' ranges, per input.

    Only accepted contributions count. Pending data has not been reviewed and
    must not widen the domain the project advertises — otherwise anyone could
    make a project look broader than it is just by submitting.

    With `owner_only`, restricted to the owner's own data. The gap between the
    two is exactly what contributors added.
    """
    ranges: dict[str, list[float]] = {}
    stmt = select(Contribution.feature_ranges).where(
        Contribution.project_id == project.id,
        Contribution.status == ContributionStatus.ACCEPTED,
    )
    if owner_only:
        stmt = stmt.where(Contribution.contributor_id == project.owner_id)

    for entry in db.scalars(stmt):
        _merge(ranges, entry)
    return ranges


def observed_ranges_bulk(
    db: Session, project_ids: Iterable[int]
) -> dict[int, dict[str, list[float]]]:
    """The same union, for many projects in one query.

    Discovery scores every candidate project against an uploaded file, and
    calling `observed_ranges` per project turns one page of results into one
    query per project. Same rule as above: accepted contributions only.
    """
    ids = list(project_ids)
    if not ids:
        return {}

    out: dict[int, dict[str, list[float]]] = {project_id: {} for project_id in ids}
    rows = db.execute(
        select(Contribution.project_id, Contribution.feature_ranges).where(
            Contribution.project_id.in_(ids),
            Contribution.status == ContributionStatus.ACCEPTED,
        )
    )
    for project_id, entry in rows:
        _merge(out[project_id], entry)
    return out
