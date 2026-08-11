"""The variable registry: browse, search, propose, moderate.

Why a registry at all is argued in ARCHITECTURE.md §3. The short version: under
free-text naming, discovery by input variable — the platform's core feature —
returns nothing, because forty projects spell "cutting speed" forty ways.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from api.db import get_db
from api.deps import get_current_user, require_moderator
from api.models import User, Variable, VariableAlias, VariableStatus
from api.schemas import VariableOut, VariableProposal
from api.services.naming import normalise, similarity

router = APIRouter(prefix="/api/variables", tags=["variables"])


@router.get("", response_model=list[VariableOut])
def list_variables(
    q: str | None = Query(default=None, max_length=120),
    dimension: str | None = Query(default=None, max_length=40),
    include_proposed: bool = False,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    """Registry listing, used by the project creation wizard's input picker."""
    statuses = [VariableStatus.APPROVED]
    if include_proposed:
        statuses.append(VariableStatus.PROPOSED)

    stmt = (
        select(Variable)
        .where(Variable.status.in_(statuses))
        .options(selectinload(Variable.aliases))
    )
    if dimension:
        stmt = stmt.where(Variable.dimension == dimension)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Variable.key.ilike(like),
                Variable.display_name.ilike(like),
                Variable.symbol.ilike(like),
            )
        )
    return list(db.scalars(stmt.order_by(Variable.display_name).limit(limit)))


@router.get("/match", response_model=list[dict])
def match_columns(
    columns: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
):
    """Suggest a registry variable for each column heading of an uploaded file.

    Returns a ranked list per column with a confidence, never a single verdict.
    The front end must present this as a score the user confirms — "4/4 inputs,
    one by approximate match, please check" is honest where "compatible" is
    not, and a wrong match here silently fits a model to the wrong column.
    """
    variables = list(
        db.scalars(
            select(Variable)
            .where(Variable.status == VariableStatus.APPROVED)
            .options(selectinload(Variable.aliases))
        )
    )

    out = []
    for column in columns[:100]:
        norm = normalise(column)
        scored = []
        for variable in variables:
            # An exact hit on the key, the display name or a registered alias
            # is certainty; anything else is a suggestion to be confirmed.
            candidates = {normalise(variable.key), normalise(variable.display_name)}
            candidates.update(a.alias for a in variable.aliases)
            if norm and norm in candidates:
                scored.append((1.0, variable))
                continue
            best = max((similarity(norm, c) for c in candidates), default=0.0)
            if best >= 0.5:
                scored.append((best, variable))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        out.append(
            {
                "column": column,
                "normalised": norm,
                "matches": [
                    {
                        "variable": VariableOut.model_validate(v).model_dump(),
                        "confidence": round(score, 3),
                        "exact": score >= 1.0,
                    }
                    for score, v in scored[:3]
                ],
            }
        )
    return out


@router.post("", response_model=VariableOut, status_code=status.HTTP_201_CREATED)
def propose_variable(
    payload: VariableProposal,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a quantity the registry does not have.

    It is usable immediately by its author and enters moderation in parallel.
    Blocking until approval would turn the registry's completeness into the
    reason the first researcher with an unusual measurement walks away.
    """
    if db.scalar(select(Variable.id).where(Variable.key == payload.key)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A variable with key '{payload.key}' already exists.",
        )

    variable = Variable(
        key=payload.key,
        display_name=payload.display_name.strip(),
        symbol=payload.symbol,
        unit=payload.unit,
        dimension=payload.dimension,
        kind=payload.kind,
        penalised_sign=payload.penalised_sign,
        description=payload.description,
        status=VariableStatus.PROPOSED,
        proposed_by_id=user.id,
    )
    db.add(variable)
    db.flush()

    seen: set[str] = set()
    for raw in [payload.display_name, *payload.aliases]:
        alias = normalise(raw)
        if alias and alias not in seen:
            seen.add(alias)
            db.add(
                VariableAlias(variable_id=variable.id, alias=alias, source="proposal")
            )

    db.commit()
    db.refresh(variable)
    return variable


@router.get("/pending", response_model=list[VariableOut])
def pending_variables(
    db: Session = Depends(get_db), _: User = Depends(require_moderator)
):
    return list(
        db.scalars(
            select(Variable)
            .where(Variable.status == VariableStatus.PROPOSED)
            .order_by(Variable.created_at)
        )
    )


@router.post("/{variable_id}/approve", response_model=VariableOut)
def approve_variable(
    variable_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_moderator),
):
    variable = db.get(Variable, variable_id)
    if variable is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such variable.")
    variable.status = VariableStatus.APPROVED
    db.commit()
    db.refresh(variable)
    return variable
