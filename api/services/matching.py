"""Matching the column headings of an uploaded file to registry variables.

Used in two places that must agree: the standalone `/api/variables/match`
endpoint, and the mapping step of an upload. One implementation, so a column
that matches on one screen matches on the other.

The output is always a *ranked list with confidences*, never a single verdict.
That is deliberate: a wrong match is not a cosmetic problem — it fits the model
to the wrong column, silently, and nothing downstream would look broken. The
interface has to present a score the user confirms, and "4/4 inputs matched,
one of them approximately — please check" is the honest phrasing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.models import Variable, VariableStatus
from api.services.naming import extract_unit, normalise, similarity

#: Below this, a candidate is not worth showing. Tuned to be permissive: the
#: user confirms every match anyway, and a missing suggestion is more annoying
#: than an extra one.
MIN_CONFIDENCE = 0.5


@dataclass
class Match:
    variable: Variable
    confidence: float
    exact: bool
    #: Set when the column heading carries a unit that disagrees with the
    #: variable's. Not fatal — plenty of headings have no unit at all, and the
    #: units may simply need converting — but it is the strongest available
    #: signal that a name match is wrong.
    unit_conflict: str | None = None


def candidate_forms(variable: Variable) -> set[str]:
    """Every normalised string this variable should answer to."""
    forms = {normalise(variable.key), normalise(variable.display_name)}
    if variable.symbol:
        forms.add(normalise(variable.symbol))
    forms.update(alias.alias for alias in variable.aliases)
    return {form for form in forms if form}


def approved_variables(db: Session, *, include_ids: set[int] | None = None) -> list[Variable]:
    """The registry, optionally plus specific proposed variables.

    `include_ids` exists so a project using a still-unmoderated quantity can
    still have its columns matched against it.
    """
    stmt = select(Variable).options(selectinload(Variable.aliases))
    if include_ids:
        stmt = stmt.where(
            (Variable.status == VariableStatus.APPROVED) | Variable.id.in_(include_ids)
        )
    else:
        stmt = stmt.where(Variable.status == VariableStatus.APPROVED)
    return list(db.scalars(stmt))


def match_column(column: str, variables: list[Variable]) -> list[Match]:
    """Rank registry variables against one column heading, best first."""
    norm = normalise(column)
    unit = extract_unit(column)
    matches: list[Match] = []

    for variable in variables:
        forms = candidate_forms(variable)
        if norm and norm in forms:
            confidence, exact = 1.0, True
        else:
            best = max((similarity(norm, form) for form in forms), default=0.0)
            if best < MIN_CONFIDENCE:
                continue
            confidence, exact = best, False

        conflict = None
        if unit and variable.unit and normalise(unit) != normalise(variable.unit):
            conflict = f"file says {unit}, registry says {variable.unit}"
        matches.append(Match(variable, confidence, exact, conflict))

    matches.sort(key=lambda m: (m.confidence, m.exact), reverse=True)
    return matches


def match_columns(columns: list[str], variables: list[Variable]) -> dict[str, list[Match]]:
    return {column: match_column(column, variables) for column in columns}


def suggest_mapping(
    wanted: list[Variable], columns: list[str], variables: list[Variable]
) -> dict[str, dict]:
    """Propose one column per wanted variable, without reusing a column twice.

    Greedy over confidence rather than per-variable independently: two of a
    project's inputs can both look plausible against the same heading, and
    quietly mapping one column to both would fit a model on a duplicated
    column. Assigning the strongest pairing first and taking that column out of
    play is the cheap fix.
    """
    scores: list[tuple[float, str, Variable]] = []
    wanted_ids = {variable.id for variable in wanted}
    for column in columns:
        for match in match_column(column, variables):
            if match.variable.id in wanted_ids:
                scores.append((match.confidence, column, match.variable))
    scores.sort(key=lambda item: item[0], reverse=True)

    taken_columns: set[str] = set()
    assigned: dict[str, dict] = {}
    for confidence, column, variable in scores:
        if variable.key in assigned or column in taken_columns:
            continue
        assigned[variable.key] = {
            "column": column,
            "confidence": round(confidence, 3),
            "exact": confidence >= 1.0,
        }
        taken_columns.add(column)

    for variable in wanted:
        assigned.setdefault(
            variable.key, {"column": None, "confidence": 0.0, "exact": False}
        )
    return assigned
