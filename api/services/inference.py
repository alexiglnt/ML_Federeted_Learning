"""Applying a model that has already been published.

The one place a stored `FittedModel` turns back into predictions, used by the
prediction endpoint and by the transfer score of ARCHITECTURE.md §5.3. It is
one place on purpose: the rule below about looking coefficients up **by key**
is the kind of thing that stays correct in the copy someone is reading and
quietly rots in the copy they are not.

Nothing here refits anything. That is the entire point of the transfer score —
the published model applied as it stands, to data it has never seen.
"""

from __future__ import annotations

import pickle
from typing import Callable

import numpy as np

from api.models import FittedModel
from api.services import storage

Predictor = Callable[[np.ndarray], np.ndarray]


def predictor_for(model: FittedModel, feature_keys: list[str]) -> Predictor:
    """A callable mapping rows of inputs to predictions.

    `feature_keys` must be in the project's declared input order, which is the
    order the design matrix was built in.

    Coefficients are looked up **by variable key**, never by position in the
    stored dict. That dict came back through JSONB, whose key order is not
    something to rely on, and a permuted lookup produces a confident wrong
    number with nothing to show for it.
    """
    if model.coefficients:
        intercept = float(model.coefficients["intercept"])
        coef = model.coefficients.get("coef", {})
        missing = [key for key in feature_keys if key not in coef]
        if missing:
            raise RuntimeError(
                f"this model has no coefficient for {', '.join(missing)}; it was "
                f"fitted on a different set of inputs"
            )
        weights = np.array([float(coef[key]) for key in feature_keys], dtype=float)

        def predict(X: np.ndarray) -> np.ndarray:
            return intercept + np.asarray(X, float) @ weights

        return predict

    if not model.artefact_path:
        raise RuntimeError("this model has neither coefficients nor a stored estimator")

    # The pickle was written by this application, into a directory only it
    # writes to. It is not user input.
    estimator = pickle.loads(storage.absolute_path(model.artefact_path).read_bytes())

    def predict_estimator(X: np.ndarray) -> np.ndarray:
        return np.asarray(estimator.predict(np.asarray(X, float)), dtype=float)

    return predict_estimator


def predict_one(model: FittedModel, feature_keys: list[str], x: list[float]) -> float:
    """One row in, one number out."""
    return float(predictor_for(model, feature_keys)(np.asarray([x], dtype=float))[0])
