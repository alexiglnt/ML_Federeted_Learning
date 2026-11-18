"""Checks on fitting and scoring that need no database or HTTP.

    docker compose exec app python tests/check_engines.py

The scores are the part of this codebase most likely to be quietly wrong:
a leave-one-lab-out number that silently falls back to ordinary
cross-validation, or a training R² presented as performance, misleads every
reader without anything looking broken.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.models import Engine  # noqa: E402
from api.services import engines  # noqa: E402

ok = True


def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


FEATURES = ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"]
SIGNS = [-1.0, -1.0, 1.0, 1.0]


def lab(seed, n, offset=0.0):
    """One lab's measurements. `offset` shifts its response, standing in for
    the systematic disagreement between measurement methods."""
    rng = np.random.default_rng(seed)
    scale = np.array([10.0, 20.0, 40.0, 0.17])
    X = rng.normal(size=(n, 4)) * scale + scale
    y = -175.0 + X @ np.array([-9.8, -12.5, 0.21, 0.03]) + offset
    y = y + rng.normal(scale=12.0, size=n)
    return X.tolist(), y.tolist()


print("== a linear engine on well-behaved data ==")
X, y = lab(1, 40)
result = engines.fit(
    Engine.LINEAR, X, y,
    feature_keys=FEATURES, penalised_signs=SIGNS, target_key="residual_stress_axial",
)
check("coefficients published", result.coefficients is not None)
check("equation published", bool(result.equation), str(result.equation)[:70])
check("no pickled artefact for a linear fit", result.artefact is None)
check("training R2 is high", (result.metrics["r2_train"] or 0) > 0.9,
      f"{result.metrics['r2_train']:.4f}")
check("out-of-sample R2 computed", result.metrics["r2_cv"] is not None,
      f"{result.metrics['r2_cv']:.4f}")
check("leave-one-lab-out is absent without groups",
      result.metrics["r2_leave_one_lab_out"] is None)
check("recovers the intercept roughly", abs(result.coefficients["intercept"] + 175) < 40,
      f"{result.coefficients['intercept']:.1f}")

print("\n== the cross-validation scheme follows the sample size ==")
small = engines.fit(Engine.LINEAR, *lab(2, 12), feature_keys=FEATURES,
                    penalised_signs=SIGNS, target_key="t")
big = engines.fit(Engine.LINEAR, *lab(3, 80), feature_keys=FEATURES,
                  penalised_signs=SIGNS, target_key="t")
check("leave-one-out on few rows", small.metrics["cv_scheme"] == "leave-one-out",
      small.metrics["cv_scheme"])
check("5-fold on many rows", big.metrics["cv_scheme"] == "5-fold", big.metrics["cv_scheme"])

print("\n== leave-one-lab-out ==")
# Three labs, one of which measures with a large systematic offset — the XRD
# versus hole-drilling problem. Ordinary cross-validation mixes its rows into
# every fold and barely notices; leave-one-lab-out must notice.
Xa, ya = lab(10, 25)
Xb, yb = lab(11, 25)
Xc, yc = lab(12, 25, offset=400.0)
X_all = Xa + Xb + Xc
y_all = ya + yb + yc
groups = [1] * 25 + [2] * 25 + [3] * 25

pooled = engines.fit(
    Engine.LINEAR, X_all, y_all, feature_keys=FEATURES, penalised_signs=SIGNS,
    target_key="t", groups=groups,
)
lolo = pooled.metrics["r2_leave_one_lab_out"]
cv = pooled.metrics["r2_cv"]
check("leave-one-lab-out computed with 3 groups", lolo is not None, str(lolo))
check("three sources recorded", pooled.metrics["n_sources"] == 3, str(pooled.metrics["n_sources"]))
check("it is harsher than ordinary cross-validation on a divergent lab",
      lolo is not None and cv is not None and lolo < cv, f"lolo={lolo:.3f} vs cv={cv:.3f}")

# With labs that agree, the two should be close: the metric must not simply be
# pessimistic by construction.
Xd, yd = lab(13, 25)
agreeing = engines.fit(
    Engine.LINEAR, Xa + Xb + Xd, ya + yb + yd, feature_keys=FEATURES,
    penalised_signs=SIGNS, target_key="t", groups=[1] * 25 + [2] * 25 + [3] * 25,
)
check("agreeing labs give a leave-one-lab-out close to cross-validation",
      abs(agreeing.metrics["r2_leave_one_lab_out"] - agreeing.metrics["r2_cv"]) < 0.15,
      f"lolo={agreeing.metrics['r2_leave_one_lab_out']:.3f} vs "
      f"cv={agreeing.metrics['r2_cv']:.3f}")

print("\n== a single lab cannot produce the metric ==")
alone = engines.fit(Engine.LINEAR, Xa, ya, feature_keys=FEATURES, penalised_signs=SIGNS,
                    target_key="t", groups=[1] * 25)
check("null rather than an invented number",
      alone.metrics["r2_leave_one_lab_out"] is None)
check("and it says so through n_sources", alone.metrics["n_sources"] == 1)

print("\n== hyperparameters are selected, not assumed ==")
piml_fit = engines.fit(Engine.PIML, X, y, feature_keys=FEATURES, penalised_signs=SIGNS,
                       target_key="t")
check("a lambda was chosen", "lambda" in piml_fit.hyperparams, str(piml_fit.hyperparams.get("lambda")))
check("the sweep is recorded for the reader", "lambda_scan_cv_r2" in piml_fit.hyperparams)
ridge_fit = engines.fit(Engine.RIDGE, X, y, feature_keys=FEATURES, penalised_signs=SIGNS,
                        target_key="t")
check("an alpha was chosen", "alpha" in ridge_fit.hyperparams, str(ridge_fit.hyperparams.get("alpha")))

print("\n== flexible engines ==")
for engine in (Engine.RF, Engine.GBM, Engine.GPR):
    fitted = engines.fit(engine, X, y, feature_keys=FEATURES, penalised_signs=SIGNS,
                         target_key="t")
    check(f"{engine.value} fits", fitted.metrics["r2_cv"] is not None,
          f"cv R2 {fitted.metrics['r2_cv']:.3f}")
    check(f"{engine.value} stores an estimator rather than an equation",
          fitted.artefact is not None and fitted.equation is None)

print("\n== a constant target is refused a score rather than given a fake one ==")
flat = engines.fit(Engine.LINEAR, X, [42.0] * len(X), feature_keys=FEATURES,
                   penalised_signs=SIGNS, target_key="t")
check("R2 is None when the target never varies", flat.metrics["r2_train"] is None)

print("\n== the published equation drops terms that are not there ==")
text = engines.format_equation("y", 1.5, ["a", "b", "c"], [2.0, 0.0, -3.0])
check("zero coefficient omitted", "b" not in text, text)
check("signs read naturally", "- 3" in text and "+ 2" in text, text)

print("\n== the benchmark compares every engine and suggests a sensible one ==")
X_lin, y_lin = lab(7, 25)
rows = engines.benchmark(X_lin, y_lin, penalised_signs=SIGNS)
check("one row per engine", len(rows) == len(Engine), str(len(rows)))
check("every engine scored out of sample",
      all(r["r2_cv"] is not None for r in rows),
      str({r["engine"]: r["r2_cv"] and round(r["r2_cv"], 3) for r in rows}))
check("no leave-one-lab-out without groups",
      all(r["r2_leave_one_lab_out"] is None for r in rows))
suggestion = engines.suggest_engine({"t": rows})
check("linear data gets a linear-family suggestion",
      suggestion["suggested"] in ("linear", "piml", "ridge"), str(suggestion))
check("basis is cross-validation without groups", suggestion["basis"] == "r2_cv")

rng = np.random.default_rng(3)
X_nl = rng.uniform(-3, 3, size=(80, 2))
y_nl = np.sin(2 * X_nl[:, 0]) * 50 + (X_nl[:, 1] ** 2) * 10 + rng.normal(scale=1.0, size=80)
rows_nl = engines.benchmark(X_nl.tolist(), y_nl.tolist(), penalised_signs=[None, None])
suggestion_nl = engines.suggest_engine({"t": rows_nl})
check("strongly non-linear data gets a flexible engine",
      suggestion_nl["suggested"] in ("gbm", "rf", "gpr"), str(suggestion_nl))

XA, yA = lab(11, 10)
XB, yB = lab(12, 10, offset=5.0)
rows_g = engines.benchmark(XA + XB, yA + yB, penalised_signs=SIGNS,
                           groups=[1] * 10 + [2] * 10)
check("leave-one-lab-out computed with two labs",
      all(r["r2_leave_one_lab_out"] is not None for r in rows_g if not r.get("error")))
check("basis switches to leave-one-lab-out",
      engines.suggest_engine({"t": rows_g})["basis"] == "r2_leave_one_lab_out")

tied = [{"engine": "gpr", "r2_cv": 0.91}, {"engine": "piml", "r2_cv": 0.90},
        {"engine": "linear", "r2_cv": 0.70}]
check("a tie within the margin goes to the simpler engine",
      engines.suggest_engine({"t": tied})["suggested"] == "piml")
check("no scores means no suggestion",
      engines.suggest_engine({"t": []})["suggested"] is None)

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
