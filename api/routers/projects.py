"""Creating and reading projects.

A project is a declaration: these are the quantities I measure, this is what I
predict. Everything else on the platform hangs off that declaration — which
files can be matched to it, who may contribute, what a model is fitted on.

Discovery (faceted search, "match my file") is lot 4 and lives elsewhere; the
listing here is deliberately plain.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.config import settings
from api.db import get_db
from api.deps import (
    access_role,
    can_read_raw_data,
    can_use_model,
    get_current_user,
    get_current_user_optional,
    require_project_owner,
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
    ContributorOut,
    DetectedColumnOut,
    FacetsOut,
    MatchFileResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectInputOut,
    ProjectMatchOut,
    ProjectSummary,
    ProjectTargetOut,
    ProjectUpdate,
    VariableOut,
)
from api.services import coverage, discovery, storage
from api.services.matching import approved_variables
from api.services.slug import unique_slug
from api.services.tabular import ParseError, parse_upload

router = APIRouter(prefix="/api/projects", tags=["projects"])

#: Kept in step with the upload path — a file you can match should be a file you
#: can then go on to contribute.
ALLOWED_MATCH_SUFFIXES = {".csv", ".txt", ".tsv", ".xlsx", ".xlsm"}


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
    observed = coverage.observed_ranges(db, project)
    owner_ranges = coverage.observed_ranges(db, project, owner_only=True)
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
                observed_min=(observed.get(item.variable.key) or [None, None])[0],
                observed_max=(observed.get(item.variable.key) or [None, None])[1],
                owner_min=(owner_ranges.get(item.variable.key) or [None, None])[0],
                owner_max=(owner_ranges.get(item.variable.key) or [None, None])[1],
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
    material: list[str] = Query(default=[]),
    process: list[str] = Query(default=[]),
    input: list[str] = Query(default=[]),
    target: list[str] = Query(default=[]),
    min_rows: int | None = Query(default=None, ge=0),
    has_model: bool | None = Query(default=None),
    sort: str = Query(default="recent", pattern="^(recent|rows)$"),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """Faceted listing.

    Repeated `input` parameters accumulate — a project must declare every one of
    them — because the question behind that filter is "which projects can use
    the columns I have". Every other facet is a set of alternatives.
    """
    found = discovery.search(
        db, q=q, materials=material, processes=process,
        inputs=input, targets=target, min_rows=min_rows,
        has_model=has_model, sort=sort, limit=limit,
    )
    return [_summary(db, project) for project in found]


@router.get("/facets", response_model=FacetsOut)
def list_facets(db: Session = Depends(get_db)):
    """Filter values that exist, with counts. Declared before /{slug}."""
    return FacetsOut(**discovery.facets(db))


@router.post("/match", response_model=MatchFileResponse)
async def match_file(
    file: UploadFile = File(...),
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """Rank projects by how well they fit a file. Open to anyone.

    Deliberately not behind a login: this is how a researcher finds out whether
    contributing is worth it, and asking them to open an account before they can
    even check compatibility puts the cost before the reason.

    **Nothing is stored.** The file is parsed in memory and discarded with the
    response — no staging, no database row, no audit entry. Deciding whether to
    hand over unpublished measurements should not require handing them over
    first, so the compatibility check is not itself a disclosure.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_MATCH_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{suffix or 'unknown'}'. Use a CSV, a "
            f"tab-separated text file, or an .xlsx spreadsheet.",
        )

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"This file is larger than the "
            f"{settings.max_upload_bytes // (1024 * 1024)} MB limit.",
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")

    try:
        table = parse_upload(file.filename or "upload", data)
    except ParseError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    # A user's own proposed quantities are matchable for them, the same rule the
    # upload path follows — otherwise the escape hatch of §3 stops working the
    # moment someone tries to find a project with it.
    own_proposals = (
        {
            variable.id
            for variable in db.scalars(
                select(Variable).where(Variable.proposed_by_id == viewer.id)
            )
        }
        if viewer
        else set()
    )
    registry = approved_variables(db, include_ids=own_proposals)
    detected, matches = discovery.match_projects(db, table, registry, limit=limit)

    claimed = {item.column for item in detected}
    return MatchFileResponse(
        filename=storage.clean_label(file.filename or "upload"),
        parse_report=table.report(),
        detected=[
            DetectedColumnOut(
                variable_key=item.variable_key,
                column=item.column,
                confidence=item.confidence,
                exact=item.exact,
                unit_conflict=item.unit_conflict,
                n_values=len(item.values),
            )
            for item in detected
        ],
        unmatched_columns=[c for c in table.columns if c not in claimed],
        matches=[
            ProjectMatchOut(
                project=_summary(db, entry.pop("project")),
                **entry,
            )
            for entry in matches
        ],
    )


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


@router.get("/{slug}/contributors", response_model=list[ContributorOut])
def list_contributors(slug: str, db: Session = Depends(get_db)):
    """Who contributed, publicly.

    Only accepted contributions, and never the file or its name — the credit
    is public, the data is not. A pending contribution is not shown at all: it
    has not been reviewed, and listing it would advertise a claim the owner has
    not agreed to.
    """
    project = _load_full(db, slug)
    rows = db.execute(
        select(Contribution, User)
        .join(User, User.id == Contribution.contributor_id)
        .where(
            Contribution.project_id == project.id,
            Contribution.status == ContributionStatus.ACCEPTED,
        )
        .order_by(Contribution.submitted_at)
    ).all()
    return [
        ContributorOut(
            name=user.full_name,
            institution=user.institution,
            n_rows=contribution.n_rows,
            measurement_method=contribution.measurement_method,
            mode=contribution.mode,
            contributed_at=contribution.submitted_at,
        )
        for contribution, user in rows
    ]


@router.patch("/{slug}", response_model=ProjectDetail)
def update_project(
    slug: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit a project. Owner only.

    Inputs and targets cannot be changed here, only their bounds and priors.
    Adding or removing an input would invalidate every column mapping already
    recorded against this project, silently, and re-mapping historical
    contributions is not something the owner can do on their contributors'
    behalf. A different set of inputs is a different project.
    """
    project = _load_full(db, slug)
    require_project_owner(db, project, user)

    for field in (
        "title", "description", "material", "process",
        "visibility", "main_engine", "accepts_federated", "licence", "status",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(project, field, value)

    if payload.input_bounds:
        by_key = {item.variable.key: item for item in project.inputs}
        unknown = set(payload.input_bounds) - set(by_key)
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Not an input of this project: {', '.join(sorted(unknown))}.",
            )
        for key, bounds in payload.input_bounds.items():
            item = by_key[key]
            if "expected_min" in bounds:
                item.expected_min = bounds["expected_min"]
            if "expected_max" in bounds:
                item.expected_max = bounds["expected_max"]
            if "penalised_sign" in bounds:
                item.penalised_sign = bounds["penalised_sign"]

    db.commit()
    return _detail(db, _load_full(db, slug), user)


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
