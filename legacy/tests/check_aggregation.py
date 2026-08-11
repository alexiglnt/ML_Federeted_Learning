"""L'agrégation depuis les sommes donne-t-elle le modèle des données réunies ?

C'est la promesse centrale de l'architecture. Le serveur ne reçoit que ``D'D``,
``D'y``, ``y'y`` et ``n``, et doit pourtant retrouver les coefficients qu'on
aurait obtenus en mettant les mesures des deux laboratoires dans un seul
tableau. Si ce contrôle passe, la confidentialité ne coûte rien en exactitude —
ce qui est l'argument qui distingue ce dispositif d'un FedAvg approché.

Le contrôle vérifie aussi qu'aucune mesure et aucune somme ne se retrouve dans
le fichier de modèle publié.

    python tests/check_aggregation.py <fixture.json> [dossier-magasin]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.fit_pretrained import (FEATURES, PENALISED_SIGN,  # noqa: E402
                                  fit_ols, fit_piml, load_titanium)

if len(sys.argv) < 2:
    raise SystemExit("usage : python tests/check_aggregation.py <fixture.json> "
                     "[magasin]")
FIXTURE = Path(sys.argv[1])
STORE = Path(sys.argv[2] if len(sys.argv) > 2
             else os.environ.get("DEAM_FL_STORE") or (ROOT / "server" / "store"))

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
target = fixture["target"]
model = json.loads((STORE / "models" / "model_v2.json").read_text(encoding="utf-8"))
tm = model["targets"][target]

# --- les données réunies, comme si tout avait été téléversé -----------------
df = load_titanium()
X = np.vstack([df[FEATURES].to_numpy(float), np.asarray(fixture["X"], float)])
y = np.concatenate([df[target].to_numpy(float),
                    np.asarray(fixture["y"], float)])
signs = np.array([PENALISED_SIGN[f] for f in FEATURES])

failures = 0


def check(label: str, got: float, want: float, tol: float) -> None:
    global failures
    delta = abs(got - want)
    ok = delta <= tol
    if not ok:
        failures += 1
    print(f"{'OK  ' if ok else 'FAIL'}  {label:<38} "
          f"sommes={got:14.6f}  réunies={want:14.6f}  d={delta:.2e}")


def assert_true(label: str, condition: bool) -> None:
    global failures
    if not condition:
        failures += 1
    print(f"{'OK  ' if condition else 'FAIL'}  {label}")


print(f"{len(y)} conditions réunies "
      f"({len(df)} du laboratoire + {len(fixture['y'])} du collègue)")
check("n", tm["n_train"], len(y), 0)

# --- linéaire, dans l'espace centré-réduit des données réunies -------------
mean, std = X.mean(axis=0), X.std(axis=0)
std[std == 0] = 1.0
Xz = (X - mean) / std
for j, feature in enumerate(FEATURES):
    check(f"scaler.mean[{feature}]", tm["scaler"]["mean"][j], mean[j], 1e-8)
    check(f"scaler.std[{feature}]", tm["scaler"]["std"][j], std[j], 1e-8)

theta_linear = fit_ols(Xz, y)
check("linear.intercept", tm["engines"]["linear"]["intercept"],
      theta_linear[0], 1e-6)
for j, feature in enumerate(FEATURES):
    check(f"linear.coef[{feature}]", tm["engines"]["linear"]["coef"][j],
          theta_linear[j + 1], 1e-6)

# --- PIML, sur variables brutes -------------------------------------------
lam = tm["engines"]["piml"]["lambda"]
theta_piml = fit_piml(X, y, lam, signs)
check("piml.intercept", tm["engines"]["piml"]["intercept"], theta_piml[0], 1e-4)
for j, feature in enumerate(FEATURES):
    check(f"piml.coef[{feature}]", tm["engines"]["piml"]["coef"][j],
          theta_piml[j + 1], 1e-4)


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / ss_tot


# --- scores d'apprentissage, calculés sans jamais voir les données ---------
check("linear train R2", tm["engines"]["linear"]["train"]["R2"],
      r2(y, theta_linear[0] + Xz @ theta_linear[1:]), 1e-6)
check("linear train RMSE", tm["engines"]["linear"]["train"]["RMSE"],
      float(np.sqrt(np.mean((y - (theta_linear[0] + Xz @ theta_linear[1:])) ** 2))),
      1e-5)
check("piml train R2", tm["engines"]["piml"]["train"]["R2"],
      r2(y, theta_piml[0] + X @ theta_piml[1:]), 1e-5)

# --- la grandeur non concernée ne doit pas avoir bougé --------------------
other = [t for t in model["targets"] if t != target]
if other:
    v1 = json.loads((STORE / "models" / "model_v1.json").read_text(encoding="utf-8"))
    name = other[0]
    assert_true(
        f"{name}, sans contribution, garde ses coefficients de la v1",
        np.allclose(model["targets"][name]["engines"]["piml"]["coef"],
                    v1["targets"][name]["engines"]["piml"]["coef"], atol=1e-9))

# --- le R² LOO doit être retiré, pas laissé périmé ------------------------
assert_true("le R² LOO de la v1 n'est pas reconduit tel quel sur la v2",
            tm["engines"]["linear"]["loo"] == {}
            and "loo_note" in tm["engines"]["linear"])

# --- rien de confidentiel dans le fichier publié -------------------------
wire = json.dumps(model)
leaks = sum(1 for value in y if f"{value:.6f}" in wire)
assert_true(f"aucune mesure dans le modèle publié ({leaks} fuite(s))", leaks == 0)
assert_true("les sommes suffisantes restent privées",
            all(key not in wire for key in ("dtd", "dty", "yty")))
assert_true("le magasin privé n'est pas publiable tel quel",
            (STORE / "stats" / "aggregate_v2.json").exists())

print(f"\n{'AGRÉGATION EXACTE' if failures == 0 else f'{failures} ÉCART(S)'}")
sys.exit(0 if failures == 0 else 1)
