"""Uploading measurements to a project, in two steps.

Step one parses the file and sets it aside without recording anything. Step two
takes a confirmed column mapping and commits it.

Two steps rather than one because the mapping cannot be trusted to a guess.
Matching "Vc (m/min)" to cutting speed is easy; matching an ambiguous heading
to the wrong input produces a model fitted to the wrong column, with nothing
visibly wrong anywhere. So the server proposes, the user confirms, and the
preview exists so a misread decimal mark or header row is seen rather than
discovered months later.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.config import settings
from api.db import SessionLocal, get_db, utcnow
from api.deps import (
    get_current_user,
    grant_contributor_access,
    require_project_owner,
    revoke_contributor_access_if_unearned,
)
from api.models import (
    AuditLog,
    Contribution,
    ContributionMode,
    ContributionStatus,
    Dataset,
    FederatedStats,
    FittedModel,
    ModelTrack,
    ModelVersion,
    Project,
    ProjectInput,
    ProjectStatus,
    ProjectTarget,
    TrainingJob,
    User,
    Variable,
)
from api.schemas import (
    AccessLogEntry,
    ContributionOut,
    ContributionReview,
    DatasetCommit,
    FederatedCommit,
    MappingSuggestion,
    PoolabilityOut,
    ReviewResult,
    TrainingJobOut,
    UploadPreview,
    ValidationOut,
)
from api.services import federated, poolability, scoring, storage, training
from api.services.dataset import build_and_validate
from api.services.matching import approved_variables, suggest_mapping
from api.services.tabular import ParseError, numeric_columns, parse_upload

router = APIRouter(prefix="/api/projects/{slug}", tags=["uploads"])

PREVIEW_ROWS = 8
ALLOWED_SUFFIXES = {".csv", ".txt", ".tsv", ".xlsx", ".xlsm"}


def _load_project(db: Session, slug: str) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.slug == slug)
        .options(
            selectinload(Project.inputs).selectinload(ProjectInput.variable),
            selectinload(Project.targets).selectinload(ProjectTarget.variable),
        )
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such project.")
    return project


def _project_variables(project: Project) -> list[Variable]:
    return [item.variable for item in project.inputs] + [
        item.variable for item in project.targets
    ]


@router.post("/uploads", response_model=UploadPreview)
async def upload_preview(
    slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _load_project(db, slug)
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This project is archived and is not taking data."
        )

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{suffix or 'unknown'}'. Upload a CSV, a "
            f"tab-separated text file, or an .xlsx spreadsheet.",
        )

    # Read with a cap rather than trusting Content-Length, which the client
    # controls. One byte over the limit is enough to know it is over.
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

    # A project may use a variable still awaiting moderation; its columns must
    # still be matchable.
    registry = approved_variables(
        db, include_ids={variable.id for variable in _project_variables(project)}
    )
    suggested = suggest_mapping(_project_variables(project), table.columns, registry)

    token = storage.stash(
        data,
        project_id=project.id,
        user_id=user.id,
        filename=file.filename or "upload",
    )

    return UploadPreview(
        upload_token=token,
        filename=storage.clean_label(file.filename or "upload"),
        parse_report=table.report(),
        columns=table.columns,
        numeric_columns=numeric_columns(table),
        preview_rows=table.rows[:PREVIEW_ROWS],
        suggested_mapping={
            key: MappingSuggestion(**value) for key, value in suggested.items()
        },
    )


@router.post(
    "/datasets", response_model=ContributionOut, status_code=status.HTTP_201_CREATED
)
def commit_dataset(
    slug: str,
    payload: DatasetCommit,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _load_project(db, slug)

    if payload.mode == ContributionMode.FEDERATED:
        # The federated path computes its sufficient statistics in the browser
        # and never uploads a file at all, so it does not come through here.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A federated contribution is made by POSTing summary statistics to "
            ".../federated, not by uploading a file.",
        )

    # ⚠️ ARCHITECTURE.md §5.5. A contributor who sent sums and now shares their
    # file must *convert* that contribution, not create a second one — otherwise
    # the same measurements enter the reference model twice, once through the
    # sums and once through the rows, and nothing about the result looks broken.
    # Refusing here is what makes the trap unreachable rather than merely
    # documented.
    existing_federated = db.scalar(
        select(Contribution).where(
            Contribution.project_id == project.id,
            Contribution.contributor_id == user.id,
            Contribution.mode == ContributionMode.FEDERATED,
            Contribution.status != ContributionStatus.WITHDRAWN,
        )
    )
    if existing_federated is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already have a federated contribution to this project "
            f"(#{existing_federated.id}). Upload your file to "
            f".../contributions/{existing_federated.id}/share to convert it, "
            f"which replaces its summary statistics with the rows. If this is "
            f"genuinely different data, withdraw that contribution first.",
        )

    try:
        data, original_filename = storage.claim(
            payload.upload_token, project_id=project.id, user_id=user.id
        )
    except LookupError as error:
        raise HTTPException(status.HTTP_410_GONE, str(error)) from error

    try:
        table = parse_upload(original_filename, data)
    except ParseError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    built = build_and_validate(
        project, table, payload.mapping, min_rows=settings.min_contribution_rows
    )
    if not built.report.ok:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This file cannot be used yet:\n" + "\n".join(built.report.errors),
        )

    digest = storage.content_hash(data)
    clash = db.scalar(
        select(Dataset)
        .join(Contribution, Dataset.contribution_id == Contribution.id)
        .where(
            Contribution.project_id == project.id,
            Dataset.content_hash == digest,
            Contribution.status != ContributionStatus.WITHDRAWN,
        )
    )
    if clash is not None:
        # The same measurements counted twice weigh twice in the fit, and
        # nothing about the resulting model would look wrong.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This exact file has already been submitted to this project.",
        )

    # Scored on arrival rather than at review time, so the owner opens a queue
    # that already has its numbers, and so the transfer score records the model
    # as it stood when the data landed. Never fatal: a contribution that cannot
    # be scored is still a contribution. See ARCHITECTURE.md §5.3.
    transfer, refit = scoring.score_contribution(db, project, built)

    # The owner's own data needs no review: reviewing yourself is theatre. Any
    # other contributor lands pending, which is what stops someone unlocking a
    # model by uploading noise.
    is_owner = project.owner_id == user.id
    contribution = Contribution(
        project_id=project.id,
        contributor_id=user.id,
        mode=ContributionMode.SHARED,
        status=ContributionStatus.ACCEPTED if is_owner else ContributionStatus.PENDING,
        n_rows=built.report.n_rows_usable,
        measurement_method=payload.measurement_method,
        notes=payload.notes,
        feature_ranges=built.report.feature_ranges,
        transfer_score=transfer,
        refit_score=refit,
        reviewed_at=utcnow() if is_owner else None,
        reviewed_by_id=user.id if is_owner else None,
    )
    db.add(contribution)
    db.flush()

    path = storage.store_dataset(
        data, project_id=project.id, suffix=Path(original_filename).suffix.lower()
    )
    db.add(
        Dataset(
            contribution_id=contribution.id,
            original_filename=original_filename,
            stored_path=storage.relative_path(path),
            content_hash=digest,
            n_rows=built.report.n_rows_usable,
            n_cols=len(table.columns),
            column_mapping=payload.mapping,
            parse_report={**table.report(), "validation": built.report.to_dict()},
        )
    )

    # A draft project becomes active once it holds data the owner accepted:
    # only then is there something to contribute to.
    if is_owner and project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.ACTIVE

    db.add(
        AuditLog(
            actor_id=user.id,
            action="dataset.upload",
            object_type="contribution",
            object_id=contribution.id,
            detail={
                "project": project.slug,
                "n_rows": built.report.n_rows_usable,
                "filename": original_filename,
            },
        )
    )
    # Accepted data changes the model, so retrain now rather than waiting to be
    # asked. Only for data that is actually in — a pending contribution must
    # not move anything until the owner has reviewed it.
    job_id = None
    if contribution.status == ContributionStatus.ACCEPTED:
        job_id = training.queue_training(db, project.id, kind="dataset-added").id

    db.commit()
    storage.discard(payload.upload_token)

    if job_id is not None:
        background.add_task(training.run_job, SessionLocal, job_id)

    return ContributionOut(
        id=contribution.id,
        project_slug=project.slug,
        contributor_name=user.full_name,
        mode=contribution.mode,
        status=contribution.status,
        n_rows=contribution.n_rows,
        measurement_method=contribution.measurement_method,
        notes=contribution.notes,
        feature_ranges=contribution.feature_ranges,
        submitted_at=contribution.submitted_at,
        original_filename=original_filename,
        validation=ValidationOut(**built.report.to_dict()),
        transfer_score=contribution.transfer_score,
        refit_score=contribution.refit_score,
        reviewed_at=contribution.reviewed_at,
        review_note=contribution.review_note,
    )


@router.post(
    "/federated", response_model=ContributionOut, status_code=status.HTTP_201_CREATED
)
def commit_federated(
    slug: str,
    payload: FederatedCommit,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Contribute summary statistics instead of measurements.

    This is the mode the original site was built around: the fitting runs in the
    contributor's browser and only ``n``, ``D'D``, ``D'y`` and ``y'y`` are
    transmitted. Those four are additive across labs, so the reference model is
    refitted **exactly** — not averaged — as if the pooled rows had been
    available (ARCHITECTURE.md §5.1).

    What this mode does and does not buy, stated plainly because the interface
    has to say it too (§4): the contributor is credited, their data widens the
    published validity domain, and it feeds the reference model. It does **not**
    feed the main model — a Gaussian process has no summary that could carry it
    — and it does **not** unlock model access. Access is the counterpart of
    sharing data, and no data was shared.
    """
    project = _load_project(db, slug)
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This project is archived and is not taking data."
        )
    if not project.accepts_federated:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This project does not accept contributions made without sharing data.",
        )

    inputs = sorted(project.inputs, key=lambda item: item.position)
    feature_keys = [item.variable.key for item in inputs]
    targets_by_key = {item.variable.key: item for item in project.targets}

    unknown = set(payload.stats) - set(targets_by_key)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Not a target of this project: {', '.join(sorted(unknown))}.",
        )

    problems: list[str] = []
    for key, summary in payload.stats.items():
        problems.extend(
            f"{key}: {problem}"
            for problem in federated.validate(
                summary.model_dump(),
                n_features=len(feature_keys),
                feature_ranges=payload.feature_ranges,
                feature_keys=feature_keys,
                min_rows=settings.min_contribution_rows,
            )
        )
    if problems:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "These summary statistics cannot be accepted:\n" + "\n".join(problems),
        )

    # Scores are derived here rather than trusted from the client: SSE(theta) is
    # expressible in the sums, so the server can compute the transfer score
    # itself and a contributor cannot flatter their own submission (§5.3).
    latest = db.scalar(
        select(ModelVersion)
        .where(ModelVersion.project_id == project.id)
        .options(selectinload(ModelVersion.fitted_models))
        .order_by(ModelVersion.number.desc())
        .limit(1)
    )
    published: dict[str, FittedModel] = {}
    if latest is not None:
        for model in latest.fitted_models:
            for key, target in targets_by_key.items():
                # The reference track is the one a summary can be judged
                # against; the main model may have no closed form at all.
                if model.target_variable_id == target.variable_id and (
                    model.track == ModelTrack.REFERENCE or key not in published
                ):
                    published[key] = model

    stats_payload = {key: value.model_dump() for key, value in payload.stats.items()}
    transfer, refit = federated.scores_from_stats(
        project, stats_payload, published, feature_keys,
        version_number=latest.number if latest else None,
    )

    is_owner = project.owner_id == user.id
    n_rows = max(summary.n for summary in payload.stats.values())
    contribution = Contribution(
        project_id=project.id,
        contributor_id=user.id,
        mode=ContributionMode.FEDERATED,
        status=ContributionStatus.ACCEPTED if is_owner else ContributionStatus.PENDING,
        n_rows=n_rows,
        measurement_method=payload.measurement_method,
        notes=payload.notes,
        feature_ranges={
            key: [float(bounds[0]), float(bounds[1])]
            for key, bounds in payload.feature_ranges.items()
            if key in feature_keys and len(bounds) == 2
        },
        transfer_score=transfer,
        refit_score=refit,
        reviewed_at=utcnow() if is_owner else None,
        reviewed_by_id=user.id if is_owner else None,
    )
    db.add(contribution)
    db.flush()

    for key, summary in payload.stats.items():
        db.add(
            FederatedStats(
                contribution_id=contribution.id,
                target_variable_id=targets_by_key[key].variable_id,
                n=summary.n,
                dtd=summary.dtd,
                dty=summary.dty,
                yty=summary.yty,
            )
        )

    db.add(
        AuditLog(
            actor_id=user.id,
            action="federated.submit",
            object_type="contribution",
            object_id=contribution.id,
            detail={"project": project.slug, "n_rows": n_rows,
                    "targets": sorted(payload.stats)},
        )
    )

    job_id = None
    if contribution.status == ContributionStatus.ACCEPTED:
        job_id = training.queue_training(db, project.id, kind="federated-added").id
    db.commit()

    if job_id is not None:
        background.add_task(training.run_job, SessionLocal, job_id)

    db.refresh(contribution)
    return _contribution_out(project, contribution, user.full_name)


@router.post("/contributions/{contribution_id}/share", response_model=ReviewResult)
def share_federated_contribution(
    slug: str,
    contribution_id: int,
    payload: DatasetCommit,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Turn a federated contribution into a shared one, in place.

    ⚠️ **This is the double-counting trap of ARCHITECTURE.md §5.5.** A
    contributor who sent sums and later shares their file must remain **one row
    whose mode changes**, never two rows. If a second row were created, the same
    measurements would enter the reference model twice — once through the sums,
    once through the rows — and the model would simply be wrong with nothing
    visibly broken.

    Here the summaries are deleted as the dataset is attached, so the pool is
    rebuilt from the rows alone at the next retrain. `pool_shared_data` selects
    on `mode == SHARED` and `_reference_statistics` on `mode == FEDERATED`, so
    one row can never be counted on both paths — but only because this endpoint
    moves the mode and drops the statistics together.

    Sharing is also what earns model access, so an accepted contribution that
    converts unlocks the model on the spot.
    """
    project = _load_project(db, slug)
    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such contribution.")
    if contribution.contributor_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the contributor can share their own data.",
        )
    if contribution.mode != ContributionMode.FEDERATED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This contribution already includes its data."
        )
    if contribution.status == ContributionStatus.WITHDRAWN:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This contribution has been withdrawn."
        )

    try:
        data, original_filename = storage.claim(
            payload.upload_token, project_id=project.id, user_id=user.id
        )
    except LookupError as error:
        raise HTTPException(status.HTTP_410_GONE, str(error)) from error

    try:
        table = parse_upload(original_filename, data)
    except ParseError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    built = build_and_validate(
        project, table, payload.mapping, min_rows=settings.min_contribution_rows
    )
    if not built.report.ok:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This file cannot be used yet:\n" + "\n".join(built.report.errors),
        )

    digest = storage.content_hash(data)
    clash = db.scalar(
        select(Dataset)
        .join(Contribution, Dataset.contribution_id == Contribution.id)
        .where(
            Contribution.project_id == project.id,
            Dataset.content_hash == digest,
            Contribution.status != ContributionStatus.WITHDRAWN,
        )
    )
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This exact file has already been submitted to this project.",
        )

    # The two must move together. Deleting the statistics is not tidying up:
    # leaving them behind while the mode changes is the double count.
    for entry in list(contribution.federated_stats):
        db.delete(entry)
    contribution.federated_stats = []
    contribution.mode = ContributionMode.SHARED
    contribution.n_rows = built.report.n_rows_usable
    contribution.feature_ranges = built.report.feature_ranges
    if payload.measurement_method:
        contribution.measurement_method = payload.measurement_method
    if payload.notes:
        contribution.notes = payload.notes

    path = storage.store_dataset(
        data, project_id=project.id, suffix=Path(original_filename).suffix.lower()
    )
    db.add(
        Dataset(
            contribution_id=contribution.id,
            original_filename=original_filename,
            stored_path=storage.relative_path(path),
            content_hash=digest,
            n_rows=built.report.n_rows_usable,
            n_cols=len(table.columns),
            column_mapping=payload.mapping,
            parse_report={**table.report(), "validation": built.report.to_dict()},
        )
    )
    db.flush()

    # Sharing is what earns access — but only for data that is actually in.
    granted = False
    if contribution.status == ContributionStatus.ACCEPTED:
        granted = grant_contributor_access(
            db, project, contribution.contributor_id, contribution.id
        )

    db.add(
        AuditLog(
            actor_id=user.id,
            action="contribution.share",
            object_type="contribution",
            object_id=contribution.id,
            detail={"project": project.slug, "filename": original_filename,
                    "n_rows": contribution.n_rows},
        )
    )

    job_id = None
    if contribution.status == ContributionStatus.ACCEPTED:
        job_id = training.queue_training(db, project.id, kind="contribution-shared").id
    db.commit()
    storage.discard(payload.upload_token)

    job = db.get(TrainingJob, job_id) if job_id else None
    if job_id is not None:
        background.add_task(training.run_job, SessionLocal, job_id)

    db.refresh(contribution)
    return ReviewResult(
        contribution=_contribution_out(project, contribution, user.full_name),
        access_granted=granted,
        training_job=(
            TrainingJobOut(id=job.id, status=job.status, kind=job.kind) if job else None
        ),
    )


@router.get("/contributions/{contribution_id}/download")
def download_dataset(
    slug: str,
    contribution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download a contributed file. Owner, or the contributor themselves.

    Every download is written to the audit log, and that log is visible to the
    contributor (`GET .../access-log`). The platform asks researchers to hand
    over unpublished measurements; the least it owes them is a record of who
    opened them and when.
    """
    project = _load_project(db, slug)
    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such contribution.")

    is_owner = project.owner_id == user.id
    if not is_owner and contribution.contributor_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the project owner and the contributor can read this file.",
        )
    dataset = contribution.dataset
    if dataset is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This contribution has no file — it was made without sharing data.",
        )

    try:
        data = storage.absolute_path(dataset.stored_path).read_bytes()
    except (LookupError, OSError) as error:
        raise HTTPException(
            status.HTTP_410_GONE, "The stored file is no longer readable."
        ) from error

    name = dataset.original_filename or "dataset.csv"
    if name.lower().endswith((".csv", ".txt", ".tsv")):
        data = storage.sanitise_csv(data)

    db.add(
        AuditLog(
            actor_id=user.id,
            action="dataset.download",
            object_type="contribution",
            object_id=contribution.id,
            detail={"project": project.slug, "filename": name, "by_owner": is_owner},
        )
    )
    db.commit()

    return Response(
        content=data,
        # Deliberately not text/csv: a generic type plus nosniff stops the
        # browser rendering or interpreting anything, whatever the extension.
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/access-log", response_model=list[AccessLogEntry])
def access_log(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Who has read the files on this project.

    A contributor sees the reads of **their own** file; the owner sees all of
    them. Surfacing this to contributors rather than keeping it internal is the
    point — it is the counterpart to the owner being able to read their data,
    and the kind of transparency a data protection review will ask for.
    """
    project = _load_project(db, slug)
    is_owner = project.owner_id == user.id

    mine = select(Contribution.id).where(Contribution.project_id == project.id)
    if not is_owner:
        mine = mine.where(Contribution.contributor_id == user.id)
    ids = [row for row in db.scalars(mine)]
    if not ids:
        return []

    rows = db.execute(
        select(AuditLog, User.full_name)
        .join(User, User.id == AuditLog.actor_id, isouter=True)
        .where(
            AuditLog.object_type == "contribution",
            AuditLog.object_id.in_(ids),
            AuditLog.action == "dataset.download",
        )
        .order_by(AuditLog.at.desc())
        .limit(200)
    ).all()

    return [
        AccessLogEntry(
            at=entry.at,
            actor_name=name or "unknown",
            action=entry.action,
            detail=entry.detail,
        )
        for entry, name in rows
    ]


def _contribution_out(
    project: Project, contribution: Contribution, contributor_name: str
) -> ContributionOut:
    dataset = contribution.dataset
    return ContributionOut(
        id=contribution.id,
        project_slug=project.slug,
        contributor_name=contributor_name,
        mode=contribution.mode,
        status=contribution.status,
        n_rows=contribution.n_rows,
        measurement_method=contribution.measurement_method,
        notes=contribution.notes,
        feature_ranges=contribution.feature_ranges,
        submitted_at=contribution.submitted_at,
        original_filename=dataset.original_filename if dataset else None,
        transfer_score=contribution.transfer_score,
        refit_score=contribution.refit_score,
        reviewed_at=contribution.reviewed_at,
        review_note=contribution.review_note,
    )


def _settle(
    db: Session,
    project: Project,
    contribution: Contribution,
    *,
    new_status: ContributionStatus,
    actor: User,
    note: str | None,
    action: str,
) -> tuple[bool, bool, int | None]:
    """Move a contribution to its new state and follow the consequences.

    The three consequences are what the whole review step is *for*, and they
    have to move together:

    1. **access** — shared data accepted earns model access; data that stops
       being accepted loses it, unless the same person still has other accepted
       data here. Otherwise a contributor could unlock a model and then pull
       their data back out, which is precisely the free ride review prevents.
       Federated contributions never grant access at all (§4): they feed the
       reference model and widen the domain, and that is the whole of it.
    2. **the model** — every version is a full refit from the accepted data, so
       excluding a contribution is "retrain without it" rather than an attempt
       to unpick its influence. Queued only when the accepted set actually
       changed: rejecting something that was merely pending moves no model,
       because pending data was never in one.
    3. **the record** — who decided what, and when.
    """
    was_accepted = contribution.status == ContributionStatus.ACCEPTED
    contribution.status = new_status
    contribution.reviewed_at = utcnow()
    contribution.reviewed_by_id = actor.id
    if note is not None:
        contribution.review_note = note

    # Sessions are created with autoflush=False, so this change is invisible to
    # the queries below until it is pushed. Without the flush, revoking looks at
    # a contribution that is still accepted, decides the access is earned, and
    # leaves it in place — while this function cheerfully reports a revocation.
    db.flush()

    granted = revoked = False
    if new_status == ContributionStatus.ACCEPTED:
        # Federated contributions never grant model access (§4). They feed the
        # reference model and widen the published domain, and that is all.
        if contribution.mode == ContributionMode.SHARED:
            granted = grant_contributor_access(
                db, project, contribution.contributor_id, contribution.id
            )
    else:
        revoked = revoke_contributor_access_if_unearned(
            db, project, contribution.contributor_id
        )

    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            object_type="contribution",
            object_id=contribution.id,
            detail={
                "project": project.slug,
                "status": new_status.value,
                "n_rows": contribution.n_rows,
            },
        )
    )

    accepted_set_changed = was_accepted != (new_status == ContributionStatus.ACCEPTED)
    job_id = None
    if accepted_set_changed:
        job_id = training.queue_training(db, project.id, kind=action).id
    return granted, revoked, job_id


@router.get("/contributions/{contribution_id}/poolability", response_model=PoolabilityOut)
def contribution_poolability(
    slug: str,
    contribution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The third score of ARCHITECTURE.md §5.7: preview the effect of
    accepting this pending contribution, checked live rather than cached.

    Owner only, same as the review decision itself — this is a preview of
    exactly the choice the review endpoint makes, not a public diagnostic.
    """
    project = _load_project(db, slug)
    require_project_owner(db, project, user)

    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such contribution.")

    try:
        result = poolability.score(db, project, contribution)
    except poolability.PoolabilityError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return PoolabilityOut(**result)


@router.post("/contributions/{contribution_id}/review", response_model=ReviewResult)
def review_contribution(
    slug: str,
    contribution_id: int,
    payload: ContributionReview,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accept or reject a contribution. Owner only.

    This is the defence described in ARCHITECTURE.md §4.2. "Share data → get the
    model" is otherwise an open invitation to upload noise in order to unlock a
    model, and an endpoint that silently alters a global model is poisonable.

    A rejection is not final: an owner who rejects and then reconsiders can
    accept the same row later. What the owner cannot do is reinstate something
    the *contributor* withdrew — that decision is not theirs.
    """
    project = _load_project(db, slug)
    require_project_owner(db, project, user)

    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such contribution.")
    if contribution.status == ContributionStatus.WITHDRAWN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The contributor withdrew this contribution. It is not the owner's "
            "to reinstate.",
        )

    wanted = (
        ContributionStatus.ACCEPTED
        if payload.decision == "accept"
        else ContributionStatus.REJECTED
    )
    # Idempotent: a double click must not queue a second retrain or write a
    # second audit entry for a decision that has already been taken.
    if contribution.status == wanted:
        return ReviewResult(
            contribution=_contribution_out(
                project, contribution, contribution.contributor.full_name
            )
        )

    granted, revoked, job_id = _settle(
        db, project, contribution,
        new_status=wanted, actor=user, note=payload.note,
        action=f"contribution.{payload.decision}",
    )
    db.commit()
    db.refresh(contribution)

    job = db.get(TrainingJob, job_id) if job_id else None
    if job_id is not None:
        background.add_task(training.run_job, SessionLocal, job_id)

    return ReviewResult(
        contribution=_contribution_out(
            project, contribution, contribution.contributor.full_name
        ),
        access_granted=granted,
        access_revoked=revoked,
        training_job=(
            TrainingJobOut(id=job.id, status=job.status, kind=job.kind) if job else None
        ),
    )


@router.post("/contributions/{contribution_id}/withdraw", response_model=ReviewResult)
def withdraw_contribution(
    slug: str,
    contribution_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Take a contribution back. The contributor's own decision.

    Deliberately not something the owner can do on someone's behalf — the owner
    rejects instead, which says a different thing and is recorded differently.

    Withdrawing surrenders model access along with the data, and that symmetry
    is the point: access is the counterpart of the data being there, not a
    reward for having once uploaded it.
    """
    project = _load_project(db, slug)
    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such contribution.")
    if contribution.contributor_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the contributor can withdraw their own contribution.",
        )
    if contribution.status == ContributionStatus.WITHDRAWN:
        return ReviewResult(
            contribution=_contribution_out(project, contribution, user.full_name)
        )

    _, revoked, job_id = _settle(
        db, project, contribution,
        new_status=ContributionStatus.WITHDRAWN, actor=user, note=None,
        action="contribution.withdraw",
    )
    db.commit()
    db.refresh(contribution)

    job = db.get(TrainingJob, job_id) if job_id else None
    if job_id is not None:
        background.add_task(training.run_job, SessionLocal, job_id)

    return ReviewResult(
        contribution=_contribution_out(project, contribution, user.full_name),
        access_revoked=revoked,
        training_job=(
            TrainingJobOut(id=job.id, status=job.status, kind=job.kind) if job else None
        ),
    )


@router.get("/contributions", response_model=list[ContributionOut])
def list_contributions(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Contributions to this project.

    The owner sees all of them. Anybody else sees only their own — a
    contributor never learns what other labs submitted, which is the promise
    that makes handing over unpublished measurements reasonable.
    """
    project = _load_project(db, slug)
    stmt = (
        select(Contribution)
        .where(Contribution.project_id == project.id)
        .options(selectinload(Contribution.contributor), selectinload(Contribution.dataset))
        .order_by(Contribution.submitted_at.desc())
    )
    if project.owner_id != user.id:
        stmt = stmt.where(Contribution.contributor_id == user.id)

    return [
        _contribution_out(project, contribution, contribution.contributor.full_name)
        for contribution in db.scalars(stmt)
    ]
