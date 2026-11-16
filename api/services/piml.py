"""The linear-family engines, expressed on sufficient statistics.

This is the reference implementation of the algebra the whole platform rests
on. Ported from `legacy/server/piml.py`, whose comments were in French; the
reasoning below is theirs, translated, because it records *why* the code looks
like this and that is the part a successor would otherwise have to rediscover.

The starting point
------------------
With ``D = [1, X]``, the residual sum of squares is

    SSE(theta) = y'y - 2 theta'(D'y) + theta'(D'D) theta

It depends on the data only through ``D'D``, ``D'y``, ``y'y`` and ``n``, and
those four quantities **add across labs**. Nothing in this module ever needs to
see an individual measurement. That is what makes federated aggregation an
exact refit rather than an approximation — and it is also why the reference
model track is confined to this family: a Gaussian process or a boosted tree
has no such summary, so no amount of summed statistics can fit one.

Why an active-set solver rather than L-BFGS
-------------------------------------------
The original study minimised the PIML loss with L-BFGS-B. On this data the loss
has a very flat valley — the coefficient of chip thickness is poorly determined
when the thickness only varies from 0.15 to 0.20 — and L-BFGS stopped at
visibly different points depending on how well conditioned the problem it was
handed happened to be. The observed disagreement reached 2 MPa per millimetre
on that coefficient between a fit on pooled data and the same fit on pooled
sums, when the two are mathematically identical.

The loss is convex and piecewise quadratic, so it can be solved exactly. With
the violation set held fixed the minimum has a closed form, and iterating on
that set converges in a few passes. Checked against L-BFGS-B on the seven
conditions of the study and every lambda in the sweep: same optimum to 1e-9 on
the loss, and never worse.
"""

from __future__ import annotations

import numpy as np


# --------------------------------------------------------------------------- #
# Sufficient statistics
# --------------------------------------------------------------------------- #
def sufficient_statistics(X, y) -> dict:
    """Summarise a dataset as ``n``, ``D'D``, ``D'y``, ``y'y``.

    This is exactly what a federated contributor transmits instead of their
    measurements. Note the honest limit: these sums are **not anonymous**. On
    very few rows they reveal a great deal, and on a single row they reproduce
    it exactly — which is what the minimum row count is for.
    """
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    design = np.column_stack([np.ones(len(X)), X])
    return {
        "n": int(len(y)),
        "dtd": (design.T @ design).tolist(),
        "dty": (design.T @ y).tolist(),
        "yty": float(y @ y),
    }


def parts(stats: dict) -> tuple[np.ndarray, np.ndarray, float, int]:
    return (
        np.asarray(stats["dtd"], float),
        np.asarray(stats["dty"], float),
        float(stats["yty"]),
        int(stats["n"]),
    )


def add(a: dict, b: dict) -> dict:
    """Sum two summaries — the central operation of federated aggregation."""
    return {
        "n": int(a["n"]) + int(b["n"]),
        "dtd": (np.asarray(a["dtd"], float) + np.asarray(b["dtd"], float)).tolist(),
        "dty": (np.asarray(a["dty"], float) + np.asarray(b["dty"], float)).tolist(),
        "yty": float(a["yty"]) + float(b["yty"]),
    }


def subtract(a: dict, b: dict) -> dict:
    """Remove one summary from a pool.

    ⚠️ The counterpart of `add`, and the reason the double-counting trap in
    ARCHITECTURE.md §5.5 is fixable at all: when a contributor who sent only
    sums later shares their raw file, their sums must be taken back out before
    their rows go in, or their data is counted twice and the model is silently
    wrong.
    """
    return {
        "n": int(a["n"]) - int(b["n"]),
        "dtd": (np.asarray(a["dtd"], float) - np.asarray(b["dtd"], float)).tolist(),
        "dty": (np.asarray(a["dty"], float) - np.asarray(b["dty"], float)).tolist(),
        "yty": float(a["yty"]) - float(b["yty"]),
    }


# --------------------------------------------------------------------------- #
# Solving
# --------------------------------------------------------------------------- #
def _solve(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Solve ``A x = b`` for a possibly singular Gram matrix.

    `lstsq` rather than `solve`, for two reasons. Robustness first: a
    contributor who held one variable constant in their experimental plan — a
    single cutting speed, say — makes ``A`` singular, and `solve` would raise
    where the minimum-norm solution is still usable. Precision second: forming
    the normal equations squares the condition number, and on units as
    unbalanced as these — thickness around 0.17 against speed around 40, six
    orders of magnitude across the diagonal of ``D'D`` — that matters. The SVD
    underlying `lstsq` absorbs it: the fit on sums matches the fit on pooled
    data to 1e-13, even at cond(D'D) around 8e6.

    Jacobi preconditioning was tried here and changed nothing (1e-11 on the
    loss): the SVD already does the work. Not worth the complication.
    """
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    return x


def solve_ols(stats: dict) -> np.ndarray:
    """Ordinary least squares: ``theta = (D'D)^-1 D'y``."""
    dtd, dty, _, _ = parts(stats)
    return _solve(dtd, dty)


def solve_ridge(stats: dict, alpha: float) -> np.ndarray:
    """Ridge. The intercept is never penalised — shrinking it towards zero
    would bias every prediction by the mean of the target."""
    dtd, dty, _, n = parts(stats)
    penalty = np.eye(len(dty))
    penalty[0, 0] = 0.0
    return _solve(dtd + n * alpha * penalty, dty)


def solve_piml(stats: dict, lam: float, penalised_signs, max_iter: int = 100) -> np.ndarray:
    """PIML by active set: ``MSE + lam * sum(max(0, s_j c_j)^2)``.

    With the violation set ``A`` held fixed, zeroing the gradient gives

        (D'D + n * lam * P_A) theta = D'y      with P_A = diag(0, 1_A)

    The intercept is never penalised: it carries no physical statement about
    how anything varies. Solve, recompute ``A``, and stop as soon as it stops
    moving.

    `penalised_signs` gives the *forbidden* sign per input: -1 discourages a
    negative coefficient, +1 a positive one, 0 means no prior.
    """
    signs = np.asarray(penalised_signs, float)
    dtd, dty, _, n = parts(stats)
    theta = _solve(dtd, dty)
    active = None

    for _ in range(max_iter):
        new_active = (signs * theta[1:]) > 0
        if active is not None and np.array_equal(active, new_active):
            break
        active = new_active
        penalty = np.diag(np.concatenate([[0.0], active.astype(float)]))
        theta = _solve(dtd + n * lam * penalty, dty)
    return theta


def loss_piml(stats: dict, theta: np.ndarray, lam: float, penalised_signs) -> float:
    """Value of the PIML loss — used by the regression checks."""
    signs = np.asarray(penalised_signs, float)
    violation = np.maximum(0.0, signs * theta[1:]) ** 2
    return sse(stats, theta) / int(stats["n"]) + lam * float(np.sum(violation))


# --------------------------------------------------------------------------- #
# Scores computable without the data
# --------------------------------------------------------------------------- #
def sse(stats: dict, theta: np.ndarray) -> float:
    dtd, dty, yty, _ = parts(stats)
    return float(yty - 2.0 * theta @ dty + theta @ dtd @ theta)


def train_metrics(stats: dict, theta: np.ndarray) -> dict:
    """Training R² and RMSE.

    ``SST = y'y - n * ybar^2`` where ``ybar = (D'y)[0] / n``, since the first
    column of ``D`` is all ones.
    """
    _, dty, yty, n = parts(stats)
    ybar = float(dty[0]) / n
    residual = sse(stats, theta)
    total = yty - n * ybar**2
    return {
        "R2": float(1.0 - residual / total) if total > 0 else None,
        "RMSE": float(np.sqrt(max(residual, 0.0) / n)),
        "n": n,
    }


# --------------------------------------------------------------------------- #
# Standardisation, also reconstructed from the sums
# --------------------------------------------------------------------------- #
def pooled_scaler(stats: dict) -> tuple[np.ndarray, np.ndarray]:
    """Mean and standard deviation of each input, recovered from ``D'D``.

    ``D'D[0, 1:]`` is the sum of each input and ``diag(D'D)[1:]`` the sum of
    its squares, which is enough to reconstruct the standardisation of the
    pooled data without having access to it.
    """
    dtd, _, _, n = parts(stats)
    total = dtd[0, 1:]
    squares = np.diag(dtd)[1:]
    mean = total / n
    var = np.maximum(squares / n - mean**2, 0.0)
    std = np.sqrt(var)
    std[std == 0] = 1.0
    return mean, std


def to_standardised(stats: dict, mean: np.ndarray, std: np.ndarray) -> dict:
    """Re-express the sums in standardised space.

    With ``Z = (X - m) / s`` we have ``D_z = D_x A`` for the affine matrix
    below, so ``D_z'D_z = A'(D_x'D_x)A`` and ``D_z'y = A'(D_x'y)``.
    """
    dtd, dty, yty, n = parts(stats)
    p = len(mean)
    A = np.zeros((p + 1, p + 1))
    A[0, 0] = 1.0
    for j in range(p):
        A[0, j + 1] = -mean[j] / std[j]
        A[j + 1, j + 1] = 1.0 / std[j]
    return {
        "n": n,
        "dtd": (A.T @ dtd @ A).tolist(),
        "dty": (A.T @ dty).tolist(),
        "yty": yty,
    }


def from_standardised(
    theta: np.ndarray, mean: np.ndarray, std: np.ndarray
) -> np.ndarray:
    """Map coefficients fitted on standardised inputs back to raw units.

    Needed so that a published equation reads in the units a machinist works
    in, whatever space the fit happened in.
    """
    coef = np.asarray(theta[1:], float) / std
    intercept = float(theta[0]) - float(np.sum(coef * mean))
    return np.concatenate([[intercept], coef])
