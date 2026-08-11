"""Produit le modèle global initial (version 1) publié par le site.

Ce script est le SEUL endroit où les données brutes du laboratoire sont lues.
Il en sort un fichier de poids — `server/store/models/model_v1.json` — qui est
tout ce que le site distribue. Aucune mesure n'y figure, seulement des
coefficients et des scores agrégés.

Les deux moteurs retenus sont ceux qui savent tourner dans un navigateur :

  * ``linear`` : moindres carrés sur les variables centrées-réduites, le choix
    de modélisation de l'article ;
  * ``piml``   : le même modèle linéaire, pénalisé dès qu'un coefficient prend
    un signe contraire à la physique de l'usinage, ajusté sur les variables
    BRUTES (λ n'a de sens que dans les unités physiques d'origine).

L'algèbre vient de ``server/piml.py``, partagée avec l'agrégation : c'est ce qui
garantit que la version 2 du modèle est la suite exacte de la version 1 et non
le produit d'un autre algorithme. La perte PIML est celle de
``Mathilde/Sources/methods/piml.py`` ; seule la façon de la minimiser diffère
(ensemble actif exact au lieu de L-BFGS-B), pour le même optimum à 1e-9 près sur
la perte — voir la note dans ``server/piml.py``.

Usage :
    python tools/fit_pretrained.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Le script est lancé depuis n'importe où (« python tools/fit_pretrained.py »
# comme « python Federated_Learning_Website/tools/fit_pretrained.py ») ; on
# rend donc le paquet server importable explicitement.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.piml import solve_ols, solve_piml, sufficient_statistics  # noqa: E402

# --------------------------------------------------------------------------- #
# Configuration — reprise de Mathilde/Sources/config.py
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESEARCH_DATA = (ROOT.parent / "Mathilde" / "Data" / "OUTEIRO2022"
                 / "ResidualStresses.xlsx")
import os  # noqa: E402

# Même variable que le serveur, pour que les contrôles automatiques puissent
# reconstruire un modèle initial dans un magasin jetable.
STORE = Path(os.environ.get("DEAM_FL_STORE")
             or (ROOT / "server" / "store")).resolve()
OUT_PATH = STORE / "models" / "model_v1.json"
STATS_PATH = STORE / "stats" / "aggregate_v1.json"

FEATURES = ["gamma", "r_beta", "Vc", "h"]
FEATURE_UNITS = {"gamma": "deg", "r_beta": "um", "Vc": "m/min", "h": "mm"}
TARGETS = {"SRS_L": "err_L", "SRS_T": "err_T"}

# Signe de coefficient INTERDIT par la physique de l'usinage du Ti-6Al-4V.
# Convention de config.PIML_SIGNS : la pénalité vaut max(0, signe * coef)^2,
# donc `-1` interdit un coefficient négatif et `+1` interdit un positif.
PENALISED_SIGN = {"gamma": -1.0, "r_beta": -1.0, "Vc": +1.0, "h": +1.0}

# λ retenu dans l'étude. On le fixe au lieu de le choisir par validation
# croisée : sélectionner λ sur la LOO puis publier le R² LOO de ce λ serait
# optimiste. Le balayage complet est tout de même enregistré pour information.
PIML_LAMBDA = 5.0
PIML_LAMBDA_SCAN = [0.0, 0.01, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0]


# --------------------------------------------------------------------------- #
# Lecture des données
# --------------------------------------------------------------------------- #
def load_titanium() -> pd.DataFrame:
    """Les conditions du plan d'expériences dont la contrainte a été mesurée.

    Même découpage que ``core.data.load_titanium`` : le bloc numérique commence
    à la ligne d'index 2, après les deux lignes d'en-tête fusionnées.
    """
    raw = pd.read_excel(RESEARCH_DATA, sheet_name="All data", header=None)
    block = raw.iloc[2:, [1, 2, 3, 4, 5, 6, 7, 8]].copy()
    block.columns = FEATURES + ["SRS_L", "err_L", "SRS_T", "err_T"]
    block = block.apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
    return block.dropna(subset=["SRS_L"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Moteurs
# --------------------------------------------------------------------------- #
def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Moindres carrés ordinaires ; renvoie theta = [ordonnée, coefs...]."""
    return solve_ols(sufficient_statistics(X, y))


def fit_piml(X: np.ndarray, y: np.ndarray, lam: float,
             signs: np.ndarray) -> np.ndarray:
    """Ajustement linéaire à signes contraints, depuis les données brutes."""
    return solve_piml(sufficient_statistics(X, y), lam, signs)


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #
def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """R², RMSE et MAE. Le R² est calculé à la main pour que la même formule
    serve ici et dans le navigateur (voir ``web/js/score.js``)."""
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return {
        "R2": 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "RMSE": float(np.sqrt(np.mean((y_true - y_pred) ** 2))),
        "MAE": float(np.mean(np.abs(y_true - y_pred))),
        "n": int(len(y_true)),
    }


def loo_predictions(X: np.ndarray, y: np.ndarray, fitter) -> np.ndarray:
    """Prédictions en validation croisée « un point de côté ».

    Sur 7 conditions, c'est le seul chiffre qui veut dire quelque chose : le R²
    d'apprentissage d'un modèle à 5 paramètres sur 7 points est cosmétique.
    """
    preds = np.empty(len(y), float)
    for k in range(len(y)):
        train = np.arange(len(y)) != k
        theta = fitter(X[train], y[train])
        preds[k] = theta[0] + X[k] @ theta[1:]
    return preds


# --------------------------------------------------------------------------- #
# Construction du fichier de poids
# --------------------------------------------------------------------------- #
def build_target(df: pd.DataFrame, target: str, err_col: str) -> dict:
    X_raw = df[FEATURES].to_numpy(float)
    y = df[target].to_numpy(float)
    signs = np.array([PENALISED_SIGN[f] for f in FEATURES])

    # --- linéaire, sur variables centrées-réduites (choix de l'article) ------
    mean = X_raw.mean(axis=0)
    std = X_raw.std(axis=0)
    std[std == 0] = 1.0
    Xz = (X_raw - mean) / std

    theta_lin = fit_ols(Xz, y)
    lin_loo = loo_predictions(Xz, y, fit_ols)

    # --- PIML, sur variables brutes ----------------------------------------
    piml_fitter = lambda Xt, yt: fit_piml(Xt, yt, PIML_LAMBDA, signs)
    theta_piml = piml_fitter(X_raw, y)
    piml_loo = loo_predictions(X_raw, y, piml_fitter)

    # Balayage de λ, purement informatif : montre au lecteur que la valeur
    # retenue n'est pas arbitraire, sans qu'elle soit choisie sur ces scores.
    scan = {}
    for lam in PIML_LAMBDA_SCAN:
        f = lambda Xt, yt, _lam=lam: fit_piml(Xt, yt, _lam, signs)
        scan[f"{lam:g}"] = round(metrics(y, loo_predictions(X_raw, y, f))["R2"], 4)

    return {
        "unit": "MPa",
        "n_train": int(len(y)),
        "n_contributions": 0,
        "contributors": [],
        "measurement_error_mean": float(
            pd.to_numeric(df[err_col], errors="coerce").mean()),
        "scaler": {"mean": mean.tolist(), "std": std.tolist()},
        "engines": {
            "linear": {
                "space": "standardised",
                "intercept": float(theta_lin[0]),
                "coef": theta_lin[1:].tolist(),
                "train": metrics(y, theta_lin[0] + Xz @ theta_lin[1:]),
                "loo": metrics(y, lin_loo),
            },
            "piml": {
                "space": "raw",
                "intercept": float(theta_piml[0]),
                "coef": theta_piml[1:].tolist(),
                "lambda": PIML_LAMBDA,
                "train": metrics(y, theta_piml[0] + X_raw @ theta_piml[1:]),
                "loo": metrics(y, piml_loo),
                "lambda_scan_loo_r2": scan,
            },
        },
    }


def main() -> None:
    if not RESEARCH_DATA.exists():
        raise SystemExit(f"Données introuvables : {RESEARCH_DATA}")

    df = load_titanium()
    print(f"[data] {len(df)} conditions mesurées, "
          f"{len(FEATURES)} variables d'entrée")

    model = {
        "schema": "deam-fl-model/1",
        "version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "material": "Ti-6Al-4V",
        "process": "orthogonal turning",
        "features": FEATURES,
        "feature_units": FEATURE_UNITS,
        # Convention explicitée dans le fichier lui-même : le navigateur en a
        # besoin pour réajuster PIML localement, et un lecteur humain doit
        # pouvoir la vérifier sans lire le code.
        "penalised_sign": PENALISED_SIGN,
        "penalised_sign_note": (
            "PIML penalty is lam * sum(max(0, penalised_sign * coef)^2). "
            "-1 forbids a negative coefficient, +1 forbids a positive one."),
        "targets": {},
        "provenance": {
            "initial_source": "OUTEIRO2022 — ResidualStresses.xlsx, sheet 'All data'",
            "fitted_by": "tools/fit_pretrained.py",
            "contains_raw_data": False,
        },
    }

    # Les statistiques suffisantes restent PRIVÉES : elles ne sont pas dans le
    # fichier publié, seulement dans le magasin du serveur, qui ne les sert
    # jamais. Elles ne servent qu'à l'agrégation (voir server/aggregate.py).
    stats = {
        "schema": "deam-fl-stats/1",
        "version": 1,
        "features": FEATURES,
        "targets": {},
    }

    for target, err_col in TARGETS.items():
        model["targets"][target] = build_target(df, target, err_col)
        stats["targets"][target] = {
            "pooled": sufficient_statistics(
                df[FEATURES].to_numpy(float), df[target].to_numpy(float)),
            "sources": [{"label": "OUTEIRO2022 (baseline)",
                         "n": int(len(df)), "model_version": 0}],
        }
        eng = model["targets"][target]["engines"]
        print(f"[{target}] linear  LOO R2 = {eng['linear']['loo']['R2']:+.3f}   "
              f"RMSE = {eng['linear']['loo']['RMSE']:.1f} MPa")
        print(f"[{target}] piml    LOO R2 = {eng['piml']['loo']['R2']:+.3f}   "
              f"RMSE = {eng['piml']['loo']['RMSE']:.1f} MPa  "
              f"(lambda = {eng['piml']['lambda']:g})")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(model, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    # Chemin relatif quand c'est lisible, absolu sinon : les contrôles font
    # tourner ce script sur un magasin temporaire, hors de l'arborescence.
    def shown(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    print(f"\n[out] {shown(OUT_PATH)}  (publié)")
    print(f"[out] {shown(STATS_PATH)}  (privé, jamais servi)")


if __name__ == "__main__":
    main()
