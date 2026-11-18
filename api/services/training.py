"""Training a project's models and recording the result as a version.

Every version is a **full refit from the accepted data**, not an incremental
update. That is the simplification the platform buys by holding the raw files:
excluding a contribution that turns out to be wrong, or deleting one at its
owner's request, is then just "retrain without it" rather than an attempt to
unpick its influence from a model. The original single-model site could not do
this and its aggregation code shows the cost.

Two tracks are fitted, and the reason is in ARCHITECTURE.md §5.4. Briefly:
sufficient statistics reconstruct a quadratic loss and nothing else, so a
federated contribution can never feed a Gaussian process. Rather than declaring
such contributions worthless, every project keeps a linear **reference** model
that everyone feeds, alongside the **main** model the owner chose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.config import settings
from api.db import utcnow
from api.models import (
    Contribution,
    ContributionMode,
    ContributionStatus,
    Engine,
    FederatedStats,
    FittedModel,
    JobStatus,
    ModelTrack,
    ModelVersion,
    ModelVersionSource,
    Project,
    ProjectInput,
    ProjectStatus,
    ProjectTarget,
    TrainingJob,
)
from api.services import engines, piml, storage
from api.services.dataset import BuiltData, build_and_validate
from api.services.tabular import parse_upload

log = logging.getLogger(__name__)


class TrainingError(RuntimeError):
    pass


@dataclass
class PooledData:
    feature_keys: list[str]
    #: {target_key: (X rows, y values, group label per row)}
    per_target: dict[str, tuple[list[list[float]], list[float], list[int]]]
    contribution_ids: list[int]
    n_rows: int


# --------------------------------------------------------------------------- #
# Gathering the data
# --------------------------------------------------------------------------- #
def _load_project(db: Session, project_id: int) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.inputs).selectinload(ProjectInput.variable),
            selectinload(Project.targets).selectinload(ProjectTarget.variable),
        )
    )
    if project is None:
        raise TrainingError("Project no longer exists.")
    return project


def load_contribution_rows(project: Project, contribution: Contribution) -> BuiltData | None:
    """Parse and validate one contribution's stored file, or None if it can't
    be read or no longer validates against the project.

    Split out of `pool_shared_data`'s loop so the same read-parse-validate
    step can be run on a single *pending* contribution too — a poolability
    check (api/services/poolability.py) needs exactly this, for one
    contribution rather than every accepted one.
    """
    dataset = contribution.dataset
    if dataset is None:
        return None
    try:
        data = storage.absolute_path(dataset.stored_path).read_bytes()
        table = parse_upload(dataset.original_filename, data)
        built = build_and_validate(
            project,
            table,
            dataset.column_mapping or {},
            min_rows=settings.min_contribution_rows,
        )
    except (LookupError, OSError, ValueError) as error:
        # One unreadable file must not stop the whole retrain. It is logged
        # and skipped, and the version records what actually went in — which
        # is the point of the lineage table.
        log.warning(
            "skipping contribution %s while training project %s: %s",
            contribution.id, project.slug, error,
        )
        return None
    if not built.report.ok:
        log.warning(
            "contribution %s no longer validates against project %s: %s",
            contribution.id, project.slug, built.report.errors,
        )
        return None
    return built


def pool_shared_data(db: Session, project: Project) -> PooledData:
    """Re-read every accepted shared file and stack it.

    Rows are labelled with the **contributor** they came from — not the
    contribution — which is what makes leave-one-lab-out mean what it says. One
    lab submitting two files is still one lab, and grouping by file would let a
    model be validated against a held-out dataset from the very lab it was
    trained on, which is the failure the metric exists to detect.
    """
    inputs = sorted(project.inputs, key=lambda item: item.position)
    feature_keys = [item.variable.key for item in inputs]
    target_keys = [item.variable.key for item in project.targets]
    per_target: dict[str, tuple[list, list, list]] = {
        key: ([], [], []) for key in target_keys
    }
    used: list[int] = []
    n_rows = 0

    contributions = db.scalars(
        select(Contribution)
        .where(
            Contribution.project_id == project.id,
            Contribution.status == ContributionStatus.ACCEPTED,
            Contribution.mode == ContributionMode.SHARED,
        )
        .options(selectinload(Contribution.dataset))
        .order_by(Contribution.submitted_at)
    )

    for contribution in contributions:
        built = load_contribution_rows(project, contribution)
        if built is None:
            continue

        used.append(contribution.id)
        n_rows += len(built.X)
        for key, values in built.y.items():
            X_all, y_all, groups = per_target[key]
            X_all.extend(built.X)
            y_all.extend(values)
            groups.extend([contribution.contributor_id] * len(values))

    return PooledData(feature_keys, per_target, used, n_rows)


def federated_contribution_ids(db: Session, project: Project) -> list[int]:
    """Accepted federated contributions whose statistics feed this project.

    Needed for the lineage: a federated contributor is credited exactly like
    anyone else (§4), so their contribution has to appear among a version's
    sources. Without this they would feed the reference model and then be absent
    from the record of what made it — which is the one place a reader looks to
    find out whose data a model rests on.
    """
    return list(
        db.scalars(
            select(Contribution.id)
            .join(FederatedStats, FederatedStats.contribution_id == Contribution.id)
            .where(
                Contribution.project_id == project.id,
                Contribution.status == ContributionStatus.ACCEPTED,
                Contribution.mode == ContributionMode.FEDERATED,
            )
            .distinct()
        )
    )


def _reference_statistics(
    db: Session, project: Project, target_key: str, X: list, y: list
) -> tuple[dict, int]:
    """Sufficient statistics for the reference track: shared rows plus sums.

    The additivity of ``D'D``, ``D'y``, ``y'y`` and ``n`` is what lets a
    contributor who never uploaded a file still move this model — exactly, not
    approximately. See ARCHITECTURE.md §5.1.

    No interface produces `FederatedStats` yet (that is lot 5b), so in practice
    this currently returns the shared rows alone. The merge is written here
    rather than later because it is where it belongs, and the arithmetic is
    covered by the aggregation invariant test.
    """
    stats = piml.sufficient_statistics(X, y)
    federated_count = 0

    rows = db.scalars(
        select(FederatedStats)
        .join(Contribution, FederatedStats.contribution_id == Contribution.id)
        .join(ProjectTarget, ProjectTarget.variable_id == FederatedStats.target_variable_id)
        .where(
            Contribution.project_id == project.id,
            Contribution.status == ContributionStatus.ACCEPTED,
            Contribution.mode == ContributionMode.FEDERATED,
            ProjectTarget.project_id == project.id,
        )
        .options(selectinload(FederatedStats.contribution))
    )
    for entry in rows:
        variable_key = next(
            (t.variable.key for t in project.targets if t.variable_id == entry.target_variable_id),
            None,
        )
        if variable_key != target_key:
            continue
        # Dimensions must agree or the sums are not describing this project's
        # inputs; adding them anyway would corrupt the fit silently.
        if len(entry.dtd) != len(stats["dtd"]):
            log.warning(
                "federated stats %s have the wrong shape for project %s; skipped",
                entry.id, project.slug,
            )
            continue
        stats = piml.add(
            stats,
            {"n": entry.n, "dtd": entry.dtd, "dty": entry.dty, "yty": entry.yty},
        )
        federated_count += 1

    return stats, federated_count


# --------------------------------------------------------------------------- #
# Fitting
# --------------------------------------------------------------------------- #
def reference_engine(project: Project) -> Engine:
    """Which linear-family engine the reference track uses.

    PIML when the project declares any physical prior, plain least squares
    otherwise. PIML with no priors reduces to least squares anyway, so this is
    about honesty in what gets published rather than about the numbers.
    """
    has_prior = any(item.penalised_sign for item in project.inputs)
    return Engine.PIML if has_prior else Engine.LINEAR


#: Phase messages shown to the user while a job runs. Kept here so the
#: front end displays whatever the server says rather than guessing.
PHASE_FITTING = "Fitting the models on the accepted data…"
PHASE_BENCHMARK = "Comparing the six engines on the same data…"


def train_project(
    db: Session,
    project_id: int,
    *,
    note: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> ModelVersion:
    """Fit both tracks on the accepted data and publish a new version.

    `progress` is told which phase has started. It must not touch `db`: the
    version is only committed once complete, and a progress update committed
    through the same session would publish it half-built.
    """
    report = progress or (lambda _message: None)
    report(PHASE_FITTING)
    project = _load_project(db, project_id)
    pooled = pool_shared_data(db, project)

    if pooled.n_rows < settings.min_contribution_rows:
        raise TrainingError(
            f"Not enough accepted data to fit anything: {pooled.n_rows} row(s)."
        )

    inputs = sorted(project.inputs, key=lambda item: item.position)
    signs = [item.penalised_sign for item in inputs]

    previous = db.scalar(
        select(ModelVersion.number)
        .where(ModelVersion.project_id == project.id)
        .order_by(ModelVersion.number.desc())
        .limit(1)
    )

    # Federated contributions feed the reference track only, but they are part
    # of what made this version and are credited as such.
    federated_ids = federated_contribution_ids(db, project)
    federated_rows = int(
        db.scalar(
            select(func.coalesce(func.sum(Contribution.n_rows), 0)).where(
                Contribution.id.in_(federated_ids)
            )
        )
        or 0
    ) if federated_ids else 0

    version = ModelVersion(
        project_id=project.id,
        number=(previous or 0) + 1,
        note=note,
        n_rows_total=pooled.n_rows + federated_rows,
        n_contributions=len(pooled.contribution_ids) + len(federated_ids),
    )
    db.add(version)
    db.flush()

    for contribution_id in pooled.contribution_ids + federated_ids:
        db.add(
            ModelVersionSource(
                model_version_id=version.id, contribution_id=contribution_id
            )
        )

    ref_engine = reference_engine(project)
    fitted_any = False
    benchmark_rows: dict[str, list[dict]] = {}

    for target in sorted(project.targets, key=lambda item: item.position):
        key = target.variable.key
        X, y, groups = pooled.per_target.get(key, ([], [], []))
        if len(y) < settings.min_contribution_rows:
            log.info("target %s has too few rows to fit; skipped", key)
            continue

        # ---- reference track: linear family, fed by everyone -------------- #
        stats, n_federated = _reference_statistics(db, project, key, X, y)
        reference = engines.fit(
            ref_engine,
            X,
            y,
            feature_keys=pooled.feature_keys,
            penalised_signs=signs,
            target_key=key,
            groups=groups,
        )
        if n_federated:
            # Refit on the pooled sums so federated contributions are actually
            # in the published coefficients. The cross-validated scores stay
            # those of the shared rows: leave-one-out needs to remove points
            # one at a time, and sums cannot do that. Saying so beats letting a
            # stale number be read as current.
            theta = (
                piml.solve_piml(stats, reference.hyperparams.get("lambda", 1.0), [s or 0.0 for s in signs])
                if ref_engine == Engine.PIML
                else piml.solve_ols(stats)
            )
            train = piml.train_metrics(stats, theta)
            reference.coefficients = {
                "intercept": float(theta[0]),
                "coef": {k: float(v) for k, v in zip(pooled.feature_keys, theta[1:])},
            }
            reference.equation = engines.format_equation(
                key, float(theta[0]), pooled.feature_keys, theta[1:]
            )
            mean, std = piml.pooled_scaler(stats)
            reference.scaler = {"mean": mean.tolist(), "std": std.tolist()}
            reference.metrics.update(
                {
                    "r2_train": train.get("R2"),
                    "rmse_train": train.get("RMSE"),
                    "n_train": train.get("n"),
                    "n_federated_sources": n_federated,
                    "cv_note": (
                        "Cross-validated scores cover the shared rows only. "
                        "Leave-one-out removes points one at a time, which "
                        "summed statistics cannot do."
                    ),
                }
            )
            reference.n_train = int(train.get("n") or reference.n_train)

        _store(db, version, ModelTrack.REFERENCE, target.variable_id, reference)
        fitted_any = True

        # ---- main track: the owner's engine, shared rows only ------------- #
        try:
            main = engines.fit(
                project.main_engine,
                X,
                y,
                feature_keys=pooled.feature_keys,
                penalised_signs=signs,
                target_key=key,
                groups=groups,
            )
        except Exception as error:  # noqa: BLE001 - one engine failing is not fatal
            log.warning("main engine %s failed on %s: %s", project.main_engine, key, error)
            continue
        _store(db, version, ModelTrack.MAIN, target.variable_id, main)

    if fitted_any:
        report(PHASE_BENCHMARK)
        for target in sorted(project.targets, key=lambda item: item.position):
            key = target.variable.key
            X, y, groups = pooled.per_target.get(key, ([], [], []))
            if len(y) < settings.min_contribution_rows:
                continue
            # ---- benchmark: every engine, same rows, same rules ----------- #
            # Never fatal: a comparison that fails must not cost the owner the
            # version that was just fitted.
            try:
                benchmark_rows[key] = engines.benchmark(
                    X, y, penalised_signs=signs, groups=groups
                )
            except Exception as error:  # noqa: BLE001
                log.warning("benchmark failed on %s: %s", key, error)
        if benchmark_rows:
            version.benchmark = {
                "targets": benchmark_rows,
                "suggestion": engines.suggest_engine(
                    benchmark_rows,
                    has_priors=any(item.penalised_sign for item in inputs),
                ),
                "current_engine": project.main_engine.value,
            }

    if not fitted_any:
        raise TrainingError("No target had enough usable rows to fit a model.")

    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.ACTIVE

    db.flush()
    return version


def _store(
    db: Session,
    version: ModelVersion,
    track: ModelTrack,
    target_variable_id: int,
    result: engines.FitResult,
) -> None:
    artefact_path = None
    if result.artefact:
        directory = settings.artefact_dir / str(version.project_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"v{version.number}_{track.value}_{target_variable_id}.pkl"
        path.write_bytes(result.artefact)
        artefact_path = storage.relative_path(path)

    db.add(
        FittedModel(
            version_id=version.id,
            track=track,
            target_variable_id=target_variable_id,
            engine=result.engine,
            hyperparams=result.hyperparams,
            metrics=result.metrics,
            coefficients=result.coefficients,
            scaler=result.scaler,
            equation=result.equation,
            artefact_path=artefact_path,
            n_train=result.n_train,
        )
    )


# --------------------------------------------------------------------------- #
# Running it as a job
# --------------------------------------------------------------------------- #
def run_job(session_factory, job_id: int) -> None:
    """Execute a queued training job in its own session.

    Its own session because this runs after the request that created it has
    returned, and that request's session is closed by then. Training is
    asynchronous because it has to be: a Gaussian process on a few hundred
    points is quick, symbolic regression is not, and neither belongs in a
    request cycle.
    """
    db = session_factory()
    try:
        job = db.get(TrainingJob, job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        db.commit()

        def progress(message: str) -> None:
            # A separate, short-lived session: see train_project's docstring.
            side = session_factory()
            try:
                running = side.get(TrainingJob, job_id)
                if running is not None:
                    running.log = message
                    side.commit()
            except Exception:  # noqa: BLE001 - progress is cosmetic, never fatal
                side.rollback()
            finally:
                side.close()

        try:
            version = train_project(db, job.project_id, note=job.kind, progress=progress)
            job.status = JobStatus.DONE
            job.log = f"Published version {version.number}."
            db.commit()
        except Exception as error:  # noqa: BLE001 - recorded, not raised into the worker
            db.rollback()
            job = db.get(TrainingJob, job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = str(error)[:2000]
                job.finished_at = utcnow()
                db.commit()
            log.exception("training job %s failed", job_id)
            return

        job = db.get(TrainingJob, job_id)
        if job is not None:
            job.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def queue_training(db: Session, project_id: int, kind: str = "retrain") -> TrainingJob:
    job = TrainingJob(project_id=project_id, kind=kind, status=JobStatus.QUEUED)
    db.add(job)
    db.flush()
    return job


def summarise(version: ModelVersion) -> dict[str, Any]:
    """Compact view of a version, for the timeline."""
    return {
        "number": version.number,
        "created_at": version.created_at,
        "n_rows_total": version.n_rows_total,
        "n_contributions": version.n_contributions,
        "note": version.note,
    }


def best_metric(models: list[FittedModel]) -> float | None:
    """The headline number for a version.

    Leave-one-lab-out when it exists, cross-validated R² otherwise. Never
    training R²: five parameters on seven points look excellent whatever the
    data says, and publishing that as the score would mislead every reader.
    """
    candidates = [
        m.metrics.get("r2_leave_one_lab_out") or m.metrics.get("r2_cv")
        for m in models
        if m.metrics
    ]
    values = [float(v) for v in candidates if v is not None and np.isfinite(v)]
    return max(values) if values else None
