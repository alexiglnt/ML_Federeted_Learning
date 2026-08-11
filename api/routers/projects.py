"""Creating and reading projects.

A project is a declaration: these are the quantities I measure, this is what I
predict. Everything else on the platform hangs off that declaration — which
files can be matched to it, who may contribute, what a model is fitted on.

Discovery (faceted search, "match my file") is lot 4 and lives elsewhere; the
listing here is deliberately plain.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.db import get_db
from api.deps import (
    access_role,
    can_read_raw_data,
    can_use_model,
    get_current_user,
    get_current_user_optional,
)
from api.models import (
    AccessRole,
    Contribution,
    ContributionStatus,
    ModelVersion,
    Project,
    ProjectAccess,
    ProjectInput,
    ProjectStatus,
    ProjectTarget,
    ProjectVisibility,
    User,
    Variable,
    VariableStatus,
)
from api.schemas import (
    ProjectCreate,
    ProjectDetail,
    ProjectInputOut,
    ProjectSummary,
    ProjectTargetOut,
    VariableOut,
)
from api.services.slug import unique_slug

router = APIRouter(prefix="/api/projects", tags=["projects"])


# --------------------------------------------------------------------------- #
# Assembling responses
# --------------------------------------------------------------------------- #
def _summary(db: Session, project: Project) -> ProjectSummary:
    """Counts a result card needs.

    Only *accepted* contributions count. A pending one has not been reviewed,
    and letting it inflate the headline numbers would let anyone advertise a
    project as larger than it is simply by submitting.
    """
    is_accepted = (
        Contribution.project_id == project.id,
        Contribution.status == ContributionStatus.ACCEPTED,
    )
    n_rows, n_contributors = db.execute(
        select(
            func.coalesce(func.sum(Contribution.n_rows), 0),
            func.count(func.distinct(Contribution.contributor_id)),
        ).where(*is_accepted)
    ).one()
    latest = db.scalar(
        select(func.max(ModelVersion.number)).where(
            ModelVersion.project_id == project.id
        )
    )
    return ProjectSummary(
        id=project.id,
        slug=project.slug,
        title=project.title,
        material=project.material,
        process=project.process,
        status=project.status,
        main_engine=project.main_engine,
        n_rows_total=int(n_rows or 0),
        n_contributors=int(n_contributors or 0),
        latest_version=latest,
        owner_name=project.owner.full_name if project.owner else None,
    )


def _detail(db: Session, project: Project, viewer: User | None) -> ProjectDetail:
    role = access_role(db, project, viewer)
    summary = _summary(db, project)
    return ProjectDetail(
        **summary.model_dump(),
        description=project.description,
        visibility=project.visibility,
        accepts_federated=project.accepts_federated,
        licence=project.licence,
        created_at=project.created_at,
        inputs=[
            ProjectInputOut(
                variable=VariableOut.model_validate(item.variable),
                position=item.position,
                required=item.required,
                unit=item.unit,
                expected_min=item.expected_min,
                expected_max=item.expected_max,
                penalised_sign=item.penalised_sign,
                # observed_min/max come from accepted data; there is none until
                # lot 2 ships uploads, so they stay null rather than pretending.
            )
            for item in project.inputs
        ],
        targets=[
            ProjectTargetOut(
                variable=VariableOut.model_validate(item.variable),
                position=item.position,
                unit=item.unit,
            )
            for item in project.targets
        ],
        viewer_role=role.value if role else None,
        viewer_can_use_model=can_use_model(role),
        viewer_can_read_raw_data=can_read_raw_data(role),
    )


def _load_full(db: Session, slug: str) -> Project:
    """Load a project with the relationships every response needs.

    Eager-loaded on purpose: rendering inputs and targets otherwise fires a
    query per row, and a project with a dozen inputs turns one page view into
    thirty round trips.
    """
    project = db.scalar(
        select(Project)
        .where(Project.slug == slug)
        .options(
            selectinload(Project.owner),
            selectinload(Project.inputs).selectinload(ProjectInput.variable),
            selectinload(Project.targets).selectinload(ProjectTarget.variable),
        )
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such project.")
    return project


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[ProjectSummary])
def list_projects(
    q: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """Plain listing. Faceted discovery is lot 4."""
    stmt = (
        select(Project)
        .where(Project.visibility == ProjectVisibility.PUBLIC)
        .options(selectinload(Project.owner))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Project.title.ilike(like)
            | Project.material.ilike(like)
            | Project.process.ilike(like)
        )
    return [_summary(db, project) for project in db.scalars(stmt)]


@router.get("/mine", response_model=list[ProjectSummary])
def my_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Projects I own. Declared before /{slug} so "mine" is not read as a slug."""
    stmt = (
        select(Project)
        .where(Project.owner_id == user.id)
        .options(selectinload(Project.owner))
        .order_by(Project.created_at.desc())
    )
    return [_summary(db, project) for project in db.scalars(stmt)]


@router.get("/{slug}", response_model=ProjectDetail)
def get_project(
    slug: str,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    return _detail(db, _load_full(db, slug), viewer)


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    input_keys = [item.variable_key for item in payload.inputs]
    target_keys = [item.variable_key for item in payload.targets]

    if len(set(input_keys)) != len(input_keys):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The same variable is listed twice as an input.",
        )
    if len(set(target_keys)) != len(target_keys):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The same variable is listed twice as a target.",
        )
    # A variable on both sides would let the model predict a column from
    # itself: a perfect fit that means nothing.
    overlap = set(input_keys) & set(target_keys)
    if overlap:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A variable cannot be both an input and a target: "
            f"{', '.join(sorted(overlap))}.",
        )

    wanted = set(input_keys) | set(target_keys)
    found = {
        variable.key: variable
        for variable in db.scalars(select(Variable).where(Variable.key.in_(wanted)))
    }
    missing = wanted - found.keys()
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown variable(s): {', '.join(sorted(missing))}. Propose them "
            f"first via POST /api/variables.",
        )

    # A proposed variable is usable by the person who proposed it while it
    # waits for moderation — that is the whole point of the escape hatch. It is
    # not usable by everyone else, or the registry would fill with unreviewed
    # near-duplicates of quantities that already exist.
    for key, variable in found.items():
        if (
            variable.status == VariableStatus.PROPOSED
            and variable.proposed_by_id != user.id
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Variable '{key}' is awaiting moderation and cannot be used yet.",
            )
        if variable.status == VariableStatus.REJECTED:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Variable '{key}' was rejected from the registry.",
            )

    slug = unique_slug(
        payload.title,
        lambda candidate: db.scalar(
            select(Project.id).where(Project.slug == candidate)
        )
        is not None,
    )

    project = Project(
        slug=slug,
        owner_id=user.id,
        title=payload.title.strip(),
        description=payload.description,
        material=payload.material,
        process=payload.process,
        visibility=payload.visibility,
        # Draft until it has data: a project with no measurements has no model
        # to offer and nothing to contribute to.
        status=ProjectStatus.DRAFT,
        main_engine=payload.main_engine,
        accepts_federated=payload.accepts_federated,
        licence=payload.licence,
    )
    db.add(project)
    db.flush()

    for position, item in enumerate(payload.inputs):
        variable = found[item.variable_key]
        db.add(
            ProjectInput(
                project_id=project.id,
                variable_id=variable.id,
                # Position is the contract. A contribution whose columns are
                # permuted would otherwise fit silently wrong coefficients.
                position=position,
                required=item.required,
                unit=item.unit or variable.unit,
                expected_min=item.expected_min,
                expected_max=item.expected_max,
                # Falls back to the registry's suggestion, which is only a
                # default — the authoritative prior is this project's.
                penalised_sign=(
                    item.penalised_sign
                    if item.penalised_sign is not None
                    else variable.penalised_sign
                ),
            )
        )

    for position, item in enumerate(payload.targets):
        variable = found[item.variable_key]
        db.add(
            ProjectTarget(
                project_id=project.id,
                variable_id=variable.id,
                position=position,
                unit=item.unit or variable.unit,
            )
        )

    db.add(
        ProjectAccess(project_id=project.id, user_id=user.id, role=AccessRole.OWNER)
    )
    db.commit()

    return _detail(db, _load_full(db, slug), user)
