"""The two scores an owner reads before accepting a contribution (§5.3).

They answer different questions and they are only useful as a pair:

  **transfer**  the project's published model, applied to the new data as it
                stands, with no refitting. *Does our model already work on
                someone else's bench?*

  **refit**     a model fitted on the contributor's rows alone and scored by
                cross-validation. *Are these measurements predictable at all?*

How to read them — this is the part that matters, and the review interface
repeats it because getting it wrong is expensive:

  transfer good                → consistent with what is already here. Accept.
  transfer poor, refit good    → clean data from a physical regime the model
                                 does not cover. **This is the most valuable
                                 contribution there is**, because it is what
                                 extends the validity domain. Do not reject it
                                 for the poor transfer score.
  transfer poor, refit poor    → noise. This is what review exists to catch.

Both are computed when the contribution arrives, and the transfer score records
which version it was measured against — a score against "the model" means
nothing once the model has moved.

For a *federated* contribution the server can recompute the transfer score
itself from the sufficient statistics, since SSE(theta) is expressible in D'D,
D'y and y'y (§5.1). Nothing produces those yet (lot 5b), so this module handles
the shared case and says so where it cannot.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.models import FittedModel, ModelTrack, ModelVersion, Project
from api.services import engines, training
from api.services.dataset import BuiltData

log = logging.getLogger(__name__)


def _latest_version(db: Session, project: Project) -> ModelVersion | None:
    return db.scalar(
        select(ModelVersion)
        .where(ModelVersion.project_id == project.id)
        .options(selectinload(ModelVersion.fitted_models))
        .order_by(ModelVersion.number.desc())
        .limit(1)
    )


def _model_for_target(
    version: ModelVersion, target_variable_id: int
) -> FittedModel | None:
    """The model to judge a contribution against: the main track if there is
    one, the reference track otherwise.

    The main track is what the project actually publishes as its model, so it is
    the honest thing to test against. A project whose main engine failed to fit
    still has its reference model, and a transfer score from that beats no score
    at all.
    """
    candidates = [m for m in version.fitted_models if m.target_variable_id == target_variable_id]
    for track in (ModelTrack.MAIN, ModelTrack.REFERENCE):
        for model in candidates:
            if model.track == track:
                return model
    return None


def transfer_score(
    db: Session, project: Project, built: BuiltData
) -> dict[str, Any]:
    """Apply the published model to the new rows. No refitting, by definition."""
    version = _latest_version(db, project)
    if version is None:
        return {
            "version": None,
            "per_target": {},
            "note": (
                "This project had no published model when the contribution "
                "arrived, so there was nothing to transfer."
            ),
        }

    X = np.asarray(built.X, dtype=float)
    per_target: dict[str, Any] = {}

    for target in project.targets:
        key = target.variable.key
        y_values = built.y.get(key)
        if not y_values:
            continue
        model = _model_for_target(version, target.variable_id)
        if model is None:
            continue
        try:
            from api.services import inference  # local: keeps the import graph flat

            predicted = inference.predictor_for(model, built.feature_keys)(X)
        except Exception as error:  # noqa: BLE001 - reported, never fatal to an upload
            log.warning("transfer score failed for %s on %s: %s", key, project.slug, error)
            per_target[key] = {"error": str(error)[:200]}
            continue

        y = np.asarray(y_values, dtype=float)
        per_target[key] = {
            "r2": engines.r2(y, predicted),
            "rmse": engines.rmse(y, predicted),
            "n": int(len(y)),
            "track": model.track.value,
            "engine": model.engine.value,
        }

    return {"version": version.number, "per_target": per_target, "note": None}


def refit_score(project: Project, built: BuiltData) -> dict[str, Any]:
    """Fit the contributor's rows on their own and cross-validate.

    Deliberately fitted with the *linear-family* reference engine rather than
    the project's main engine, whatever that is. The question being asked is
    "are these measurements internally consistent", and a Gaussian process on
    seven points answers that with a flattering number no matter what the data
    says. A linear fit that cross-validates well is evidence; a GPR that does is
    mostly evidence about the GPR.
    """
    engine = training.reference_engine(project)
    inputs = sorted(project.inputs, key=lambda item: item.position)
    signs = [item.penalised_sign for item in inputs]

    per_target: dict[str, Any] = {}
    for target in project.targets:
        key = target.variable.key
        y_values = built.y.get(key)
        if not y_values:
            continue
        try:
            result = engines.fit(
                engine,
                built.X,
                y_values,
                feature_keys=built.feature_keys,
                penalised_signs=signs,
                target_key=key,
            )
        except Exception as error:  # noqa: BLE001
            log.warning("refit score failed for %s on %s: %s", key, project.slug, error)
            per_target[key] = {"error": str(error)[:200]}
            continue

        per_target[key] = {
            "r2_cv": result.metrics.get("r2_cv"),
            "rmse_cv": result.metrics.get("rmse_cv"),
            "cv_scheme": result.metrics.get("cv_scheme"),
            "n": result.n_train,
        }

    return {"engine": engine.value, "per_target": per_target}


def score_contribution(
    db: Session, project: Project, built: BuiltData
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Both scores for one arriving contribution.

    Never raises: a contribution that cannot be scored is still a contribution,
    and refusing an upload because a diagnostic failed would be the wrong trade.
    The owner sees whatever was computable and reviews on the rest.
    """
    try:
        transfer = transfer_score(db, project, built)
    except Exception as error:  # noqa: BLE001
        log.exception("transfer scoring failed on %s", project.slug)
        transfer = {"version": None, "per_target": {}, "note": str(error)[:200]}
    try:
        refit = refit_score(project, built)
    except Exception as error:  # noqa: BLE001
        log.exception("refit scoring failed on %s", project.slug)
        refit = {"engine": None, "per_target": {}, "note": str(error)[:200]}
    return transfer, refit
