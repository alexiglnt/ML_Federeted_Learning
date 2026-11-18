"""Training a project, and reading its versions and models.

The access split enforced here is the one in ARCHITECTURE.md §4.1: **metrics
are public, the model is not**. Anyone can see that a project holds 47 rows
from five labs and scores 0.81 out of sample; only the owner and accepted
contributors get the coefficients. That asymmetry is what gives a visitor a
reason to contribute — hide the metrics and nobody knows what they would be
joining.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.db import SessionLocal, get_db
from api.deps import (
    access_role,
    can_use_model,
    get_current_user,
    get_current_user_optional,
    require_project_owner,
)
from api.models import (
    Contribution,
    Engine,
    FittedModel,
    ModelVersion,
    ModelVersionSource,
    Project,
    ProjectInput,
    ProjectTarget,
    TrainingJob,
    User,
)
from api.schemas import (
    FittedModelOut,
    ModelVersionOut,
    PredictionOut,
    PredictRequest,
    PredictResponse,
    TrainingJobOut,
    VersionSourceOut,
)
from api.services import coverage, inference, training

router = APIRouter(prefix="/api/projects/{slug}", tags=["models"])


def _project(db: Session, slug: str) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.slug == slug)
        .options(selectinload(Project.targets).selectinload(ProjectTarget.variable))
    )
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such project.")
    return project


def _project_full(db: Session, slug: str) -> Project:
    """As above, plus inputs and owner — needed to predict and to export."""
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


def _resolve_version(db: Session, project: Project, number: int | None) -> ModelVersion:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.project_id == project.id)
        .options(selectinload(ModelVersion.fitted_models))
    )
    stmt = (
        stmt.where(ModelVersion.number == number)
        if number is not None
        else stmt.order_by(ModelVersion.number.desc()).limit(1)
    )
    found = db.scalar(stmt)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This project has no trained model yet."
            if number is None
            else f"Version {number} does not exist.",
        )
    return found


def _serialise_model(
    model: FittedModel, project: Project, *, reveal: bool
) -> FittedModelOut:
    target = next(
        (t for t in project.targets if t.variable_id == model.target_variable_id), None
    )
    return FittedModelOut(
        track=model.track,
        target_key=target.variable.key if target else str(model.target_variable_id),
        target_name=target.variable.display_name if target else "unknown",
        target_unit=target.unit if target else None,
        engine=model.engine,
        n_train=model.n_train,
        metrics=model.metrics or {},
        hyperparams=model.hyperparams or {},
        # Withheld unless the viewer has earned model access.
        coefficients=model.coefficients if reveal else None,
        scaler=model.scaler if reveal else None,
        equation=model.equation if reveal else None,
        opaque=not model.engine.is_federated_compatible,
    )


def _serialise_version(
    db: Session, version: ModelVersion, project: Project, *, reveal: bool
) -> ModelVersionOut:
    models = list(version.fitted_models)
    sources = db.execute(
        select(Contribution, User.full_name)
        .join(ModelVersionSource, ModelVersionSource.contribution_id == Contribution.id)
        .join(User, User.id == Contribution.contributor_id)
        .where(ModelVersionSource.model_version_id == version.id)
        .order_by(Contribution.submitted_at)
    ).all()

    return ModelVersionOut(
        number=version.number,
        created_at=version.created_at,
        note=version.note,
        n_rows_total=version.n_rows_total,
        n_contributions=version.n_contributions,
        headline_r2=training.best_metric(models),
        benchmark=version.benchmark,
        models=[_serialise_model(m, project, reveal=reveal) for m in models],
        sources=[
            VersionSourceOut(
                contribution_id=contribution.id,
                contributor_name=name,
                n_rows=contribution.n_rows,
                measurement_method=contribution.measurement_method,
                mode=contribution.mode,
            )
            for contribution, name in sources
        ],
    )


@router.get("/versions", response_model=list[ModelVersionOut])
def list_versions(
    slug: str,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """The version timeline, newest first, with its lineage.

    Public, deliberately, including who contributed and how many rows. What is
    withheld is the model itself.
    """
    project = _project(db, slug)
    reveal = can_use_model(access_role(db, project, viewer))
    versions = db.scalars(
        select(ModelVersion)
        .where(ModelVersion.project_id == project.id)
        .options(selectinload(ModelVersion.fitted_models))
        .order_by(ModelVersion.number.desc())
    )
    return [_serialise_version(db, v, project, reveal=reveal) for v in versions]


@router.get("/model", response_model=ModelVersionOut)
def latest_model(
    slug: str,
    version: int | None = None,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    project = _project(db, slug)
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.project_id == project.id)
        .options(selectinload(ModelVersion.fitted_models))
    )
    stmt = (
        stmt.where(ModelVersion.number == version)
        if version is not None
        else stmt.order_by(ModelVersion.number.desc()).limit(1)
    )
    found = db.scalar(stmt)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This project has no trained model yet."
            if version is None
            else f"Version {version} does not exist.",
        )
    reveal = can_use_model(access_role(db, project, viewer))
    return _serialise_version(db, found, project, reveal=reveal)


@router.post("/train", response_model=TrainingJobOut, status_code=status.HTTP_202_ACCEPTED)
def train(
    slug: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Queue a retrain. Owner only.

    202 rather than 200: the server accepts the request, it has not finished
    the work. Poll the job for the outcome.
    """
    project = _project(db, slug)
    require_project_owner(db, project, user)

    running = db.scalar(
        select(TrainingJob).where(
            TrainingJob.project_id == project.id,
            TrainingJob.status.in_(["queued", "running"]),
        )
    )
    if running is not None:
        # Two concurrent retrains would race to publish consecutive version
        # numbers and one would lose on the unique constraint.
        return TrainingJobOut(
            id=running.id, status=running.status, kind=running.kind,
            log="A training run is already in progress for this project.",
        )

    job = training.queue_training(db, project.id)
    db.commit()
    background.add_task(training.run_job, SessionLocal, job.id)
    return TrainingJobOut(id=job.id, status=job.status, kind=job.kind)


def _job_out(job: TrainingJob) -> TrainingJobOut:
    return TrainingJobOut(
        id=job.id, status=job.status, kind=job.kind, error=job.error, log=job.log,
        created_at=job.created_at, started_at=job.started_at,
    )


@router.get("/jobs/current", response_model=TrainingJobOut | None)
def current_job(slug: str, db: Session = Depends(get_db)):
    """The queued or running training job, if any. Public, like the scores.

    Lets a page that did not start the job — the project page right after an
    upload, a second tab, a contributor watching — show that a new version is
    on its way instead of a stale "no model yet".
    """
    project = _project(db, slug)
    job = db.scalar(
        select(TrainingJob)
        .where(
            TrainingJob.project_id == project.id,
            TrainingJob.status.in_(["queued", "running"]),
        )
        .order_by(TrainingJob.id.desc())
        .limit(1)
    )
    return None if job is None else _job_out(job)


@router.get("/jobs/{job_id}", response_model=TrainingJobOut)
def job_status(
    slug: str,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _project(db, slug)
    job = db.get(TrainingJob, job_id)
    if job is None or job.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such training job.")
    return _job_out(job)


@router.post("/predict", response_model=PredictResponse)
def predict(
    slug: str,
    payload: PredictRequest,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """Run the model on one set of cutting parameters.

    Behind the same gate as the coefficients: being able to query a model
    without limit is having the model. Out-of-domain inputs are answered rather
    than refused — the model is still the best estimate available — but the
    response says so, because a prediction outside the range the model has data
    for is a different kind of claim.
    """
    project = _project_full(db, slug)
    if not can_use_model(access_role(db, project, viewer)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Contribute your measurements to this project to use its model.",
        )

    version = _resolve_version(db, project, payload.version)
    inputs = sorted(project.inputs, key=lambda item: item.position)

    missing = [i.variable.key for i in inputs if i.variable.key not in payload.values]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Missing value(s) for: {', '.join(missing)}.",
        )
    # Order is the contract — the same ordering the design matrix was built
    # with. Reading the dict in its own order would silently permute inputs.
    feature_keys = [item.variable.key for item in inputs]
    x = [float(payload.values[key]) for key in feature_keys]

    covered = coverage.observed_ranges(db, project)
    out_of_domain = []
    for item, value in zip(inputs, x):
        bounds = covered.get(item.variable.key)
        if not bounds:
            continue
        low, high = bounds
        if value < low or value > high:
            out_of_domain.append(
                f"{item.variable.display_name} = {value:g} lies outside the range "
                f"the model has data for ({low:g} to {high:g}). The prediction is "
                f"an extrapolation."
            )

    models = [m for m in version.fitted_models if m.track == payload.track]
    if not models:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Version {version.number} has no model on the {payload.track.value} track.",
        )

    predictions = []
    for model in models:
        target = next(
            (t for t in project.targets if t.variable_id == model.target_variable_id),
            None,
        )
        try:
            value = inference.predict_one(model, feature_keys, x)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"This model could not be evaluated: {error}",
            ) from error
        predictions.append(
            PredictionOut(
                target_key=target.variable.key if target else "unknown",
                target_name=target.variable.display_name if target else "unknown",
                target_unit=target.unit if target else None,
                value=value,
                engine=model.engine,
                track=model.track,
            )
        )

    return PredictResponse(
        version=version.number, predictions=predictions, out_of_domain=out_of_domain
    )


@router.get("/export")
def export_model(
    slug: str,
    version: int | None = None,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """The model as a self-contained JSON document.

    Meant to be citable: it carries the units, the metrics, the provenance and
    the exact contributions behind the fit, so that a reader of a paper can
    tell what the numbers were fitted on. Same gate as the coefficients.
    """
    project = _project_full(db, slug)
    if not can_use_model(access_role(db, project, viewer)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Contribute your measurements to this project to export its model.",
        )
    found = _resolve_version(db, project, version)

    sources = db.execute(
        select(Contribution, User.full_name, User.institution)
        .join(ModelVersionSource, ModelVersionSource.contribution_id == Contribution.id)
        .join(User, User.id == Contribution.contributor_id)
        .where(ModelVersionSource.model_version_id == found.id)
        .order_by(Contribution.submitted_at)
    ).all()

    covered = coverage.observed_ranges(db, project)
    return {
        "schema": "mlfl-model/1",
        "project": {
            "slug": project.slug,
            "title": project.title,
            "material": project.material,
            "process": project.process,
            "licence": project.licence,
            "owner": project.owner.full_name if project.owner else None,
        },
        "version": found.number,
        "created_at": found.created_at.isoformat(),
        "inputs": [
            {
                "key": item.variable.key,
                "name": item.variable.display_name,
                "unit": item.unit,
                "position": item.position,
                "covered_range": covered.get(item.variable.key),
                "penalised_sign": item.penalised_sign,
            }
            for item in sorted(project.inputs, key=lambda i: i.position)
        ],
        "models": [
            {
                "track": model.track.value,
                "target": next(
                    (t.variable.key for t in project.targets
                     if t.variable_id == model.target_variable_id),
                    None,
                ),
                "engine": model.engine.value,
                "hyperparams": model.hyperparams,
                "coefficients": model.coefficients,
                "equation": model.equation,
                "metrics": model.metrics,
                "n_train": model.n_train,
                "note": (
                    None if model.coefficients
                    else "This engine has no closed form; use the prediction endpoint."
                ),
            }
            for model in found.fitted_models
        ],
        "provenance": {
            "n_rows_total": found.n_rows_total,
            "contributions": [
                {
                    "contributor": name,
                    "institution": institution,
                    "n_rows": contribution.n_rows,
                    "measurement_method": contribution.measurement_method,
                    "mode": contribution.mode.value,
                }
                for contribution, name, institution in sources
            ],
            "contains_raw_data": False,
            "citation_note": (
                "This model was fitted on measurements contributed by the people "
                "listed above. Cite them."
            ),
        },
    }


@router.get("/engines")
def available_engines():
    """Engines a project may choose, and whether each can absorb a federated
    contribution. The front end uses this rather than hardcoding the list."""
    return [
        {
            "key": engine.value,
            "federated_compatible": engine.is_federated_compatible,
        }
        for engine in Engine
    ]
