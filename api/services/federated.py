"""Accepting sufficient statistics from a contributor who kept their data.

A federated contribution transmits four numbers per target — ``n``, ``D'D``,
``D'y`` and ``y'y`` with ``D = [1, X]`` — and nothing else. The measurements
stay on the contributor's machine. ARCHITECTURE.md §5.1 explains why that is
enough to fit exactly rather than approximately.

Everything here exists because **the client computes those numbers**, and the
server cannot see the data they came from. Two consequences:

*Validation is not optional.* A malformed or invented summary corrupts the
reference model of every project it touches, silently, and no amount of staring
at the resulting coefficients would reveal it. So the sums are checked against
the things that must be true of any real dataset before they are stored. Most
of these checks are one line and they are the only thing standing between the
platform and a poisoned pool.

*The scores are recomputed here, not accepted from the client.* §5.3: the
transfer score is expressible in ``D'D``, ``D'y`` and ``y'y``, so the server
derives it itself. A contributor cannot flatter their own submission.
"""

from __future__ import annotations

import numpy as np

from api.models import FittedModel, Project
from api.services import piml

#: Relative slack on the algebraic identities below. Generous because the sums
#: are computed in float64 in a browser, over data whose columns differ by
#: orders of magnitude — thickness around 0.17 against speed around 40 — so the
#: rounding is real. Tight enough that fabricated numbers do not slip through.
TOLERANCE = 1e-6


def _as_stats(payload: dict) -> dict:
    return {
        "n": int(payload["n"]),
        "dtd": np.asarray(payload["dtd"], dtype=float),
        "dty": np.asarray(payload["dty"], dtype=float),
        "yty": float(payload["yty"]),
    }


def validate(
    payload: dict,
    *,
    n_features: int,
    feature_ranges: dict[str, list[float]] | None = None,
    feature_keys: list[str] | None = None,
    min_rows: int = 1,
) -> list[str]:
    """Everything that must be true of a real dataset's summary.

    Returns human-readable problems; an empty list means the summary is
    consistent with *some* dataset of the declared shape. It cannot tell whether
    that dataset is the one the contributor actually measured — nothing can —
    but it rules out summaries that describe no dataset at all.
    """
    problems: list[str] = []
    width = n_features + 1

    try:
        stats = _as_stats(payload)
    except (KeyError, TypeError, ValueError) as error:
        return [f"The summary is not readable: {error}."]

    dtd, dty, yty, n = stats["dtd"], stats["dty"], stats["yty"], stats["n"]

    # ---- shape: a permuted or wrong-sized design is the silent killer ------ #
    if dtd.shape != (width, width):
        problems.append(
            f"D'D should be {width}×{width} for a project with {n_features} "
            f"inputs, not {'×'.join(str(d) for d in dtd.shape)}. The column "
            f"order is the project's input order and it is contractual."
        )
    if dty.shape != (width,):
        problems.append(f"D'y should have {width} entries, not {dty.shape[0]}.")
    if problems:
        return problems
    if not np.all(np.isfinite(dtd)) or not np.all(np.isfinite(dty)) or not np.isfinite(yty):
        return ["The summary contains values that are not finite numbers."]

    # ---- the privacy floor ------------------------------------------------ #
    # These sums are not anonymous. On very few rows they disclose a great deal,
    # and on a single row they reproduce it exactly.
    if n < min_rows:
        problems.append(
            f"A summary over {n} row(s) is not anonymous enough to accept; at "
            f"least {min_rows} are required."
        )

    # ---- identities that hold for every real dataset ---------------------- #
    scale = max(float(np.max(np.abs(dtd))), 1.0)
    if not np.allclose(dtd, dtd.T, rtol=TOLERANCE, atol=TOLERANCE * scale):
        problems.append("D'D is not symmetric, so it is not a Gram matrix.")

    # The first column of D is all ones, so this entry counts the rows.
    if not np.isclose(dtd[0, 0], n, rtol=TOLERANCE, atol=TOLERANCE * max(n, 1)):
        problems.append(
            f"D'D[0,0] is {dtd[0, 0]:g} but should equal the row count, {n}. "
            f"The first column of the design matrix is the intercept."
        )

    symmetric = 0.5 * (dtd + dtd.T)
    smallest = float(np.min(np.linalg.eigvalsh(symmetric)))
    if smallest < -TOLERANCE * scale:
        problems.append(
            "D'D is not positive semi-definite, so no dataset produces it."
        )

    if yty < -TOLERANCE * max(abs(yty), 1.0):
        problems.append("y'y is negative, which no sum of squares can be.")

    # The residual sum of squares at the best possible fit cannot be negative.
    # This is what ties y'y to D'y and D'D: inflating y'y alone, or inventing
    # D'y, breaks it.
    if not problems:
        theta = piml.solve_ols({"n": n, "dtd": dtd, "dty": dty, "yty": yty})
        residual = piml.sse({"n": n, "dtd": dtd, "dty": dty, "yty": yty}, theta)
        if residual < -TOLERANCE * max(abs(yty), 1.0):
            problems.append(
                "The three sums are mutually inconsistent: they imply a "
                "negative residual sum of squares."
            )

    # ---- the declared ranges must match the sums -------------------------- #
    # The published validity domain is grown from these ranges, so a fabricated
    # range would widen what the project claims to cover.
    if feature_ranges and feature_keys and n > 0 and len(feature_keys) == n_features:
        totals = dtd[0, 1:]
        squares = np.diag(dtd)[1:]
        for index, key in enumerate(feature_keys):
            bounds = feature_ranges.get(key)
            if not bounds or len(bounds) != 2:
                continue
            low, high = float(bounds[0]), float(bounds[1])
            if high < low:
                problems.append(f"The range given for {key} runs backwards.")
                continue
            span = max(high - low, 0.0)
            slack = TOLERANCE * max(abs(low), abs(high), 1.0)

            mean = float(totals[index]) / n
            if not (low - slack <= mean <= high + slack):
                problems.append(
                    f"The mean of {key} implied by D'D is {mean:g}, outside the "
                    f"range {low:g} to {high:g} declared for it."
                )
                continue
            # Popoviciu: no distribution on [low, high] varies more than this.
            variance = max(float(squares[index]) / n - mean**2, 0.0)
            limit = (span / 2.0) ** 2
            if variance > limit + slack + TOLERANCE * max(limit, 1.0):
                problems.append(
                    f"{key} varies more than its declared range {low:g} to "
                    f"{high:g} allows."
                )

    return problems


def _theta_for(model: FittedModel, feature_keys: list[str]) -> np.ndarray | None:
    """Published coefficients as ``[intercept, ...]`` in project input order.

    By key, never by position — the dict came back through JSONB and its order
    is not something to rely on.
    """
    if not model.coefficients:
        return None
    coef = model.coefficients.get("coef", {})
    if any(key not in coef for key in feature_keys):
        return None
    return np.array(
        [float(model.coefficients["intercept"])] + [float(coef[k]) for k in feature_keys],
        dtype=float,
    )


def scores_from_stats(
    project: Project,
    stats_by_target: dict[str, dict],
    published: dict[str, FittedModel],
    feature_keys: list[str],
    version_number: int | None = None,
) -> tuple[dict, dict]:
    """The two scores of §5.3, computed without ever seeing the measurements.

    **Transfer** is exact: ``SSE(theta)`` is expressible in the sums, so the
    published model can be scored against data the server cannot read.

    **Refit** is honestly weaker than its shared-mode counterpart. Fitting on
    the contributor's own sums is exact, but cross-validating is not possible —
    leave-one-out has to remove points one at a time and summed statistics
    cannot do that. What is reported is therefore a *training* score, and it is
    labelled as one. Calling it cross-validated because the shared path is would
    be the more comfortable lie.
    """
    inputs = sorted(project.inputs, key=lambda item: item.position)
    signs = [item.penalised_sign or 0.0 for item in inputs]

    transfer: dict = {"version": None, "per_target": {}, "note": None}
    refit: dict = {
        "engine": "sums",
        "per_target": {},
        "note": (
            "Fitted on the contributor's own summary statistics. This is a "
            "training score, not a cross-validated one: leave-one-out removes "
            "points one at a time and summed statistics cannot."
        ),
    }

    for key, raw in stats_by_target.items():
        stats = {
            "n": int(raw["n"]),
            "dtd": np.asarray(raw["dtd"], float),
            "dty": np.asarray(raw["dty"], float),
            "yty": float(raw["yty"]),
        }

        model = published.get(key)
        if model is not None:
            theta = _theta_for(model, feature_keys)
            if theta is None:
                transfer["per_target"][key] = {
                    "error": "the published model has no closed form to transfer"
                }
            else:
                residual = piml.sse(stats, theta)
                ybar = float(stats["dty"][0]) / stats["n"]
                total = stats["yty"] - stats["n"] * ybar**2
                transfer["per_target"][key] = {
                    "r2": float(1.0 - residual / total) if total > 0 else None,
                    "rmse": float(np.sqrt(max(residual, 0.0) / stats["n"])),
                    "n": stats["n"],
                    "track": model.track.value,
                    "engine": model.engine.value,
                }
                # The version *number*, matching what the shared path records —
                # a score against "the model" means nothing once it has moved.
                transfer["version"] = version_number

        try:
            theta_local = (
                piml.solve_piml(stats, 1.0, signs)
                if any(signs)
                else piml.solve_ols(stats)
            )
            local = piml.train_metrics(stats, theta_local)
            refit["per_target"][key] = {
                "r2_train": local.get("R2"),
                "rmse_train": local.get("RMSE"),
                "n": local.get("n"),
                "cv_scheme": "none — summary statistics cannot be resampled",
            }
        except Exception as error:  # noqa: BLE001 - a diagnostic, never fatal
            refit["per_target"][key] = {"error": str(error)[:200]}

    if not transfer["per_target"]:
        transfer["note"] = (
            "This project had no published linear model to transfer when the "
            "contribution arrived."
        )
    return transfer, refit
