"""Fitting one model, and scoring it honestly.

Two families live here and they are not interchangeable:

  * the **linear family** (`linear`, `ridge`, `piml`) is fitted through
    `api.services.piml`, entirely from sufficient statistics. It produces a
    readable equation, and it is the only family a federated contribution can
    ever feed;
  * the **flexible family** (`gpr`, `gbm`, `rf`) is scikit-learn, needs the
    individual rows, and produces a pickled estimator rather than an equation.

On scoring
----------
Training R² is reported but must not be read as performance. Five parameters
fitted on seven points will look excellent whatever the data says; the original
site refused to show it alone for exactly that reason. What is worth reading is
`r2_cv` and, above all, `r2_leave_one_lab_out` — see ARCHITECTURE.md §5.6. The
latter answers the question a researcher actually has (does this model work
anywhere other than where it was built?) and no single lab can compute it.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from api.models import Engine
from api.services import piml

#: Searched by cross-validation. The PIML sweep is the one from the original
#: study, which found the useful range to sit well below the default of 5.
LAMBDA_GRID = [0.0, 0.01, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0]
ALPHA_GRID = [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0]

#: Below this many rows, leave-one-out; above it, 5-fold. Leave-one-out is the
#: only cross-validation that means anything on the handful of conditions
#: typical here, and it is affordable precisely because the datasets are small.
LOO_THRESHOLD = 30


@dataclass
class FitResult:
    engine: Engine
    n_train: int
    hyperparams: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    coefficients: dict[str, Any] | None = None
    scaler: dict[str, Any] | None = None
    equation: str | None = None
    #: Pickled estimator, for engines with no closed form to publish.
    artefact: bytes | None = None


# --------------------------------------------------------------------------- #
# Predictors
# --------------------------------------------------------------------------- #
Predictor = Callable[[np.ndarray], np.ndarray]


def _affine_predictor(theta: np.ndarray) -> Predictor:
    def predict(X: np.ndarray) -> np.ndarray:
        return theta[0] + np.asarray(X, float) @ theta[1:]

    return predict


def _fit_linear_family(
    engine: Engine, X: np.ndarray, y: np.ndarray, signs: np.ndarray, params: dict
) -> tuple[np.ndarray, Predictor]:
    """Fit in raw units and return ``theta = [intercept, coefs...]``.

    Raw rather than standardised on purpose for `linear` and `piml`: the
    published equation then reads directly in the units a machinist works in,
    and the PIML priors are statements about physical coefficients. Ridge is
    the exception — its penalty is scale dependent, so it is fitted on
    standardised inputs and mapped back afterwards.
    """
    stats = piml.sufficient_statistics(X, y)
    if engine == Engine.RIDGE:
        mean, std = piml.pooled_scaler(stats)
        theta_z = piml.solve_ridge(
            piml.to_standardised(stats, mean, std), params.get("alpha", 0.01)
        )
        theta = piml.from_standardised(theta_z, mean, std)
    elif engine == Engine.PIML:
        theta = piml.solve_piml(stats, params.get("lambda", 1.0), signs)
    else:
        theta = piml.solve_ols(stats)
    return theta, _affine_predictor(theta)


def _make_sklearn(engine: Engine, params: dict):
    """Build a scikit-learn pipeline. Inputs are standardised in every case.

    Machining inputs differ by orders of magnitude — chip thickness around 0.17
    against cutting speed around 40 — and a kernel or a distance that sees raw
    units is dominated by whichever variable happens to be measured in large
    numbers.
    """
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if engine == Engine.GPR:
        kernel = ConstantKernel(1.0) * RBF(length_scale=1.0) + WhiteKernel(
            noise_level=1.0
        )
        estimator = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            # Several restarts because the marginal likelihood is multi-modal
            # and a single one lands wherever the initial guess points.
            n_restarts_optimizer=params.get("n_restarts", 4),
            random_state=0,
        )
    elif engine == Engine.GBM:
        estimator = GradientBoostingRegressor(
            n_estimators=params.get("n_estimators", 300),
            max_depth=params.get("max_depth", 2),
            learning_rate=params.get("learning_rate", 0.05),
            random_state=0,
        )
    else:
        estimator = RandomForestRegressor(
            n_estimators=params.get("n_estimators", 300),
            min_samples_leaf=params.get("min_samples_leaf", 1),
            random_state=0,
            n_jobs=1,
        )
    return Pipeline([("scale", StandardScaler()), ("model", estimator)])


def _fit_predictor(
    engine: Engine, X: np.ndarray, y: np.ndarray, signs: np.ndarray, params: dict
) -> Predictor:
    if engine.is_federated_compatible:
        _, predict = _fit_linear_family(engine, X, y, signs, params)
        return predict
    pipeline = _make_sklearn(engine, params)
    pipeline.fit(X, y)
    return lambda Z: np.asarray(pipeline.predict(Z), float)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    y_true = np.asarray(y_true, float)
    total = float(np.sum((y_true - y_true.mean()) ** 2))
    if total <= 0:
        # Every target value identical: R² is undefined rather than zero, and
        # reporting a number here would be an invention.
        return None
    residual = float(np.sum((y_true - np.asarray(y_pred, float)) ** 2))
    return float(1.0 - residual / total)


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    diff = np.asarray(y_true, float) - np.asarray(y_pred, float)
    return float(np.sqrt(np.mean(diff**2)))


def _folds(n: int, groups: np.ndarray | None) -> list[np.ndarray]:
    """Test-index sets. Leave-one-out when small, 5-fold otherwise."""
    if groups is not None:
        return [np.where(groups == g)[0] for g in np.unique(groups)]
    if n <= LOO_THRESHOLD:
        return [np.array([i]) for i in range(n)]
    order = np.arange(n)
    rng = np.random.default_rng(0)  # deterministic: a rerun must not move the score
    rng.shuffle(order)
    return [fold for fold in np.array_split(order, 5) if len(fold)]


def cross_validated(
    engine: Engine,
    X: np.ndarray,
    y: np.ndarray,
    signs: np.ndarray,
    params: dict,
    groups: np.ndarray | None = None,
) -> tuple[float | None, float | None]:
    """Out-of-sample R² and RMSE. Returns (None, None) when not computable."""
    n = len(y)
    folds = _folds(n, groups)
    if len(folds) < 2:
        return None, None

    predictions = np.full(n, np.nan)
    for test_index in folds:
        train_index = np.setdiff1d(np.arange(n), test_index)
        if len(train_index) < 2:
            continue
        try:
            predict = _fit_predictor(engine, X[train_index], y[train_index], signs, params)
            predictions[test_index] = predict(X[test_index])
        except Exception:
            # One unfittable fold — a lab whose data is rank-deficient on its
            # own, say — should degrade the score, not abort the whole run.
            continue

    usable = np.isfinite(predictions)
    if usable.sum() < 2:
        return None, None
    return r2(y[usable], predictions[usable]), rmse(y[usable], predictions[usable])


def _select_hyperparams(
    engine: Engine, X: np.ndarray, y: np.ndarray, signs: np.ndarray
) -> dict:
    """Pick lambda or alpha by cross-validation.

    Only for the linear family: each candidate costs a full leave-one-out pass,
    which is trivial for a closed-form solve and would not be for a GPR.
    """
    if engine == Engine.PIML:
        key, grid = "lambda", LAMBDA_GRID
    elif engine == Engine.RIDGE:
        key, grid = "alpha", ALPHA_GRID
    else:
        return {}

    scan: dict[str, float | None] = {}
    best_value, best_score = grid[0], -math.inf
    for value in grid:
        score, _ = cross_validated(engine, X, y, signs, {key: value})
        scan[str(value)] = None if score is None else round(score, 4)
        if score is not None and score > best_score:
            best_value, best_score = value, score
    return {key: best_value, f"{key}_scan_cv_r2": scan}


# --------------------------------------------------------------------------- #
# The public entry point
# --------------------------------------------------------------------------- #
def fit(
    engine: Engine,
    X_rows: list[list[float]],
    y_values: list[float],
    *,
    feature_keys: list[str],
    penalised_signs: list[float | None],
    target_key: str,
    groups: list[int] | None = None,
) -> FitResult:
    """Fit one engine to one target, and score it.

    `groups` labels each row with the contribution it came from, so that
    leave-one-lab-out can be computed. It is the metric this platform exists to
    make possible, so it is worth the plumbing.
    """
    X = np.asarray(X_rows, float)
    y = np.asarray(y_values, float)
    signs = np.array([0.0 if s is None else float(s) for s in penalised_signs])
    n = len(y)

    params = _select_hyperparams(engine, X, y, signs)
    clean_params = {k: v for k, v in params.items() if not k.endswith("_scan_cv_r2")}

    result = FitResult(engine=engine, n_train=n, hyperparams=params)

    if engine.is_federated_compatible:
        theta, predict = _fit_linear_family(engine, X, y, signs, clean_params)
        stats = piml.sufficient_statistics(X, y)
        train = piml.train_metrics(stats, theta)
        result.coefficients = {
            "intercept": float(theta[0]),
            "coef": {key: float(value) for key, value in zip(feature_keys, theta[1:])},
        }
        mean, std = piml.pooled_scaler(stats)
        result.scaler = {"mean": mean.tolist(), "std": std.tolist()}
        result.equation = format_equation(
            target_key, float(theta[0]), feature_keys, theta[1:]
        )
    else:
        pipeline = _make_sklearn(engine, clean_params)
        pipeline.fit(X, y)
        predict = lambda Z: np.asarray(pipeline.predict(Z), float)  # noqa: E731
        fitted = predict(X)
        train = {"R2": r2(y, fitted), "RMSE": rmse(y, fitted), "n": n}
        result.artefact = pickle.dumps(pipeline, protocol=pickle.HIGHEST_PROTOCOL)

    r2_cv, rmse_cv = cross_validated(engine, X, y, signs, clean_params)

    r2_lolo = None
    n_groups = 0
    if groups is not None:
        group_array = np.asarray(groups)
        n_groups = len(np.unique(group_array))
        if n_groups >= 2:
            r2_lolo, _ = cross_validated(
                engine, X, y, signs, clean_params, groups=group_array
            )

    result.metrics = {
        "r2_train": train.get("R2"),
        "rmse_train": train.get("RMSE"),
        "r2_cv": r2_cv,
        "rmse_cv": rmse_cv,
        "cv_scheme": "leave-one-out" if n <= LOO_THRESHOLD else "5-fold",
        "r2_leave_one_lab_out": r2_lolo,
        "n_sources": n_groups,
        "n_train": n,
    }
    return result


def format_equation(
    target_key: str, intercept: float, feature_keys: list[str], coefficients
) -> str:
    """A readable equation in physical units.

    Terms whose coefficient rounds to nothing are dropped: a printed
    "+ 0.000·edge_radius" reads as a real effect that happens to be small,
    when it is really an absence of one.
    """
    parts = [f"{intercept:.4g}"]
    for key, value in zip(feature_keys, coefficients):
        value = float(value)
        if abs(value) < 1e-12:
            continue
        parts.append(f"{'-' if value < 0 else '+'} {abs(value):.4g}·{key}")
    return f"{target_key} = " + " ".join(parts)
