"""Whether accepting a pending contribution helps or hurts the model (§5.7).

Transfer and refit (`scoring.py`) answer "is this contribution good on its
own terms". Neither answers the question that matters once a project has more
than one contributor: *if this is accepted, does the model's honest,
cross-lab score get better or worse for everyone else too?* A row can be
perfectly self-consistent and still be the kind of outlier that wrecks
leave-one-lab-out for the rest of the pool (ARCHITECTURE.md §5.6) — that
failure mode is invisible to transfer and refit alike.

Two numbers, both against the *current* accepted pool, both shared-mode only
(§5.1: a federated contribution has no raw rows to hold out and predict):

  **own score**    a model fit on every accepted contributor except this one,
                   scored against this contribution's own rows. *Does
                   everyone else's data predict this lab?*

  **pool effect**  leave-one-lab-out R² of the accepted pool, before vs.
                   after adding this contribution as one more group. *Does
                   accepting it move the model's honest score for everyone,
                   not just for this lab?*

Computed live, on request — never cached on the `Contribution` row the way
transfer/refit are. Both of those are pinned to a version number precisely
because a stale, labelled score is still meaningful history; poolability has
no such anchor; it is a question about the *current* accepted pool, and that
pool changes underneath a pending contribution every time another one is
accepted or rejected. Caching it would go stale between two reviewers'
decisions without anything visibly wrong.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from api.models import Contribution, ContributionMode, ContributionStatus, Project
from api.services import engines, inference, training

log = logging.getLogger(__name__)


class PoolabilityError(RuntimeError):
    pass


def score(db: Session, project: Project, contribution: Contribution) -> dict[str, Any]:
    """Both poolability numbers for one pending shared contribution.

    Never raises for a single target failing to fit — the same convention as
    `scoring.score_contribution`: a contribution that cannot be scored on one
    target is still reviewable on the rest.
    """
    if contribution.mode != ContributionMode.SHARED:
        raise PoolabilityError(
            "Poolability can only be checked for shared contributions — a "
            "federated contribution never gives the server raw rows to hold "
            "out and test."
        )
    if contribution.status != ContributionStatus.PENDING:
        raise PoolabilityError(
            "Poolability is a preview for a pending decision; this "
            "contribution has already been reviewed."
        )

    candidate = training.load_contribution_rows(project, contribution)
    if candidate is None:
        return {
            "engine": None,
            "per_target": {},
            "note": (
                "This contribution's file could not be read or no longer "
                "validates against the project, so nothing could be compared."
            ),
        }

    pooled = training.pool_shared_data(db, project)
    engine = training.reference_engine(project)
    inputs = sorted(project.inputs, key=lambda item: item.position)
    signs = [item.penalised_sign for item in inputs]
    contributor_id = contribution.contributor_id

    per_target: dict[str, Any] = {}
    for key, cand_values in candidate.y.items():
        if not cand_values:
            continue
        pool_X, pool_y, pool_groups = pooled.per_target.get(key, ([], [], []))
        if not pool_y:
            per_target[key] = {
                "note": "No accepted data yet for this target to compare against."
            }
            continue

        try:
            before = engines.fit(
                engine,
                pool_X,
                pool_y,
                feature_keys=pooled.feature_keys,
                penalised_signs=signs,
                target_key=key,
                groups=pool_groups,
            )
            predict = inference.predictor_for(before, pooled.feature_keys)
            predicted = predict(np.asarray(candidate.X, dtype=float))
            own_r2 = engines.r2(np.asarray(cand_values, dtype=float), predicted)
            own_rmse = engines.rmse(np.asarray(cand_values, dtype=float), predicted)

            after = engines.fit(
                engine,
                pool_X + candidate.X,
                pool_y + cand_values,
                feature_keys=pooled.feature_keys,
                penalised_signs=signs,
                target_key=key,
                groups=pool_groups + [contributor_id] * len(cand_values),
            )
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            log.warning(
                "poolability scoring failed for %s on %s: %s", key, project.slug, error
            )
            per_target[key] = {"error": str(error)[:200]}
            continue

        pool_r2_before = before.metrics.get("r2_leave_one_lab_out")
        pool_r2_after = after.metrics.get("r2_leave_one_lab_out")
        entry: dict[str, Any] = {
            "own_r2": own_r2,
            "own_rmse": own_rmse,
            "own_n": len(cand_values),
            "pool_r2_before": pool_r2_before,
            "pool_r2_after": pool_r2_after,
            "pool_delta": (
                pool_r2_after - pool_r2_before
                if pool_r2_before is not None and pool_r2_after is not None
                else None
            ),
            "n_contributors_before": before.metrics.get("n_sources"),
            "n_contributors_after": after.metrics.get("n_sources"),
        }
        if pool_r2_before is None:
            entry["note"] = (
                "Not enough distinct contributors yet to have a baseline "
                "leave-one-lab-out score to compare against."
            )
        per_target[key] = entry

    return {"engine": engine.value, "per_target": per_target, "note": None}
