"""The load-bearing invariant: summing statistics equals pooling the data.

Run inside the application container, where numpy and the api package live:

    docker compose exec app python tests/check_aggregation.py

This is the claim the whole federated design rests on (ARCHITECTURE.md §5.1).
If it ever stops holding, contributions that never uploaded a file stop moving
the model correctly — and nothing anywhere would look broken. The original
site checked the same thing to 1e-13 and it is worth keeping checked.
"""

import sys
from pathlib import Path

import numpy as np

# Running a script puts its own directory on the path, not the project root, so
# `api` would not be importable. Fixed here rather than by asking the reader to
# remember a PYTHONPATH, because the command in the docstring should just work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services import piml  # noqa: E402

TOLERANCE = 1e-9
ok = True


def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


def lab_data(seed, n, p=4, scale=None):
    """A lab's worth of measurements, on deliberately unbalanced units.

    The scales mimic real machining inputs — chip thickness around 0.17 against
    cutting speed around 40 — because that imbalance is exactly what makes the
    normal equations badly conditioned, and the point of the check is that it
    survives that.
    """
    rng = np.random.default_rng(seed)
    scale = scale if scale is not None else np.array([10.0, 20.0, 40.0, 0.17])
    X = rng.normal(size=(n, p)) * scale + scale
    true = np.array([-9.8, -12.5, 0.21, 0.03])
    y = -175.0 + X @ true + rng.normal(scale=15.0, size=n)
    return X, y


print("== the sums add up ==")
X1, y1 = lab_data(1, 7)
X2, y2 = lab_data(2, 19)
X3, y3 = lab_data(3, 40)

pooled_X = np.vstack([X1, X2, X3])
pooled_y = np.concatenate([y1, y2, y3])

summed = piml.add(
    piml.add(piml.sufficient_statistics(X1, y1), piml.sufficient_statistics(X2, y2)),
    piml.sufficient_statistics(X3, y3),
)
direct = piml.sufficient_statistics(pooled_X, pooled_y)

check("n matches", summed["n"] == direct["n"], f"{summed['n']} vs {direct['n']}")
for key in ("dtd", "dty", "yty"):
    diff = np.max(np.abs(np.asarray(summed[key]) - np.asarray(direct[key])))
    check(f"{key} matches", diff < TOLERANCE, f"max abs diff {diff:.2e}")

print("\n== least squares on sums equals least squares on pooled rows ==")
theta_sums = piml.solve_ols(summed)
design = np.column_stack([np.ones(len(pooled_X)), pooled_X])
theta_direct, *_ = np.linalg.lstsq(design, pooled_y, rcond=None)
diff = np.max(np.abs(theta_sums - theta_direct))
check("coefficients identical", diff < 1e-8, f"max abs diff {diff:.2e}")
condition = np.linalg.cond(np.asarray(summed["dtd"]))
print(f"    (cond(D'D) = {condition:.2e}, so this is not a soft test)")

print("\n== PIML on sums equals PIML on pooled rows ==")
signs = [-1.0, -1.0, 1.0, 1.0]
for lam in (0.0, 0.1, 1.0, 5.0, 100.0):
    a = piml.solve_piml(summed, lam, signs)
    b = piml.solve_piml(direct, lam, signs)
    diff = np.max(np.abs(a - b))
    check(f"lambda={lam}", diff < 1e-8, f"max abs diff {diff:.2e}")

print("\n== the priors actually bite, and only where they should ==")
# The data here contradicts three of the four priors, so at a large lambda no
# coefficient should still be on its forbidden side.
#
# Note what "pushed towards zero" does *not* mean: a coefficient whose
# forbidden sign is positive is free to go as negative as it likes, since the
# penalty is max(0, s*c)^2 and vanishes there. Crushing the other coefficients
# can therefore make one of them grow in the permitted direction. That is the
# correct optimum, not a solver artefact — the thing to assert is the absence
# of violations, not the size of the coefficients.
free = piml.solve_piml(direct, 0.0, signs)
free_violations = [s * c for s, c in zip(signs, free[1:])]
check(
    "without a penalty the data violates its priors",
    sum(v > 0 for v in free_violations) >= 2,
    f"violations {np.round(free_violations, 3)}",
)

penalised = piml.solve_piml(direct, 1e5, signs)
violations = [s * c for s, c in zip(signs, penalised[1:])]
worst = max(violations)
check(
    "with a strong penalty no coefficient stays on its forbidden side",
    worst < 0.1,
    f"worst violation {worst:.4g}, coefficients {np.round(penalised[1:], 4)}",
)

# And the converse: priors the data already agrees with must cost nothing, at
# any lambda. If they do not, the penalty is engaging where it should not and
# every fit is quietly biased.
agreeing = [1.0 if c < 0 else -1.0 for c in free[1:]]
baseline = piml.solve_ols(direct)
for lam in (1.0, 100.0, 1e5):
    theta = piml.solve_piml(direct, lam, agreeing)
    diff = np.max(np.abs(theta - baseline))
    check(f"satisfied priors change nothing at lambda={lam:g}", diff < 1e-8,
          f"max abs diff {diff:.2e}")

print("\n== training metrics from sums equal metrics from rows ==")
metrics = piml.train_metrics(direct, theta_direct)
residual = pooled_y - design @ theta_direct
raw_r2 = 1.0 - np.sum(residual**2) / np.sum((pooled_y - pooled_y.mean()) ** 2)
raw_rmse = float(np.sqrt(np.mean(residual**2)))
check("R2 matches", abs(metrics["R2"] - raw_r2) < 1e-10, f"{metrics['R2']:.10f} vs {raw_r2:.10f}")
check("RMSE matches", abs(metrics["RMSE"] - raw_rmse) < 1e-10)

print("\n== the standardisation recovered from sums is the real one ==")
mean, std = piml.pooled_scaler(direct)
check("mean matches", np.max(np.abs(mean - pooled_X.mean(axis=0))) < 1e-9)
check("std matches", np.max(np.abs(std - pooled_X.std(axis=0))) < 1e-9)

theta_z = piml.solve_ols(piml.to_standardised(direct, mean, std))
back = piml.from_standardised(theta_z, mean, std)
check(
    "coefficients survive the round trip to standardised space and back",
    np.max(np.abs(back - theta_direct)) < 1e-7,
    f"max abs diff {np.max(np.abs(back - theta_direct)):.2e}",
)

print("\n== subtract undoes add — the double-counting guard ==")
# ARCHITECTURE.md §5.5: when a contributor who sent only sums later shares
# their file, their sums must come back out before their rows go in. If this
# arithmetic is wrong, their data is counted twice and the model is silently
# wrong.
pair = piml.add(piml.sufficient_statistics(X1, y1), piml.sufficient_statistics(X2, y2))
restored = piml.subtract(pair, piml.sufficient_statistics(X2, y2))
alone = piml.sufficient_statistics(X1, y1)
check("n restored", restored["n"] == alone["n"], f"{restored['n']} vs {alone['n']}")
for key in ("dtd", "dty", "yty"):
    diff = np.max(np.abs(np.asarray(restored[key]) - np.asarray(alone[key])))
    check(f"{key} restored", diff < TOLERANCE, f"max abs diff {diff:.2e}")

theta_restored = piml.solve_ols(restored)
theta_alone = piml.solve_ols(alone)
check(
    "and the fit is the same as if the second lab had never been added",
    np.max(np.abs(theta_restored - theta_alone)) < 1e-8,
)

print("\n== a lab with a constant input does not break the solve ==")
# Someone whose experimental plan held cutting speed fixed makes D'D singular.
# `solve` would raise; the minimum-norm solution is still usable.
X4 = np.array(lab_data(4, 8)[0])
X4[:, 2] = 40.0
y4 = lab_data(4, 8)[1]
try:
    theta = piml.solve_ols(piml.sufficient_statistics(X4, y4))
    check("singular design still solves", np.all(np.isfinite(theta)))
except Exception as error:  # noqa: BLE001
    check("singular design still solves", False, str(error))

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
