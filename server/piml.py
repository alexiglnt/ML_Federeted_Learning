"""Les deux moteurs, exprimés sur les statistiques suffisantes.

C'est l'implémentation de référence : ``tools/fit_pretrained.py`` s'en sert pour
produire le modèle initial, ``server/aggregate.py`` pour fusionner les
contributions, et ``web/js/models.js`` en est la transposition JavaScript. Une
seule définition de l'algorithme, donc les trois donnent les mêmes chiffres —
ce qui est la condition pour qu'un score obtenu dans un navigateur soit
comparable à un score publié.

Le point de départ
------------------
Avec ``D = [1, X]``, la somme des carrés des résidus s'écrit

    SSE(theta) = y'y - 2 theta'(D'y) + theta'(D'D) theta

Elle ne dépend des données que par ``D'D``, ``D'y``, ``y'y`` et ``n``, et ces
quatre quantités s'additionnent d'un laboratoire à l'autre. Tout ce qui suit
n'en manipule qu'elles : aucune fonction de ce module n'a besoin de voir une
mesure. C'est ce qui rend l'agrégation exacte plutôt qu'approchée.

Pourquoi un solveur par ensemble actif plutôt que L-BFGS
--------------------------------------------------------
L'étude minimise la perte PIML par L-BFGS-B. Sur ces données la perte a une
vallée très plate — le coefficient de ``h`` est mal déterminé, l'épaisseur ne
variant que de 0.15 à 0.20 — et L-BFGS s'y arrête à des points différents selon
le conditionnement du problème qu'on lui donne. Les écarts observés atteignaient
2 MPa par millimètre sur le coefficient de ``h`` entre un ajustement sur données
réunies et le même ajustement sur les sommes, alors que les deux devraient être
identiques.

La perte est convexe et quadratique par morceaux, ce qui permet de la résoudre
exactement. À ensemble de violations fixé, le minimum a une forme close, et
l'itération sur cet ensemble converge en quelques passes. Vérifié contre
L-BFGS-B sur les sept conditions de l'étude et tous les λ du balayage : même
optimum à 1e-9 près sur la perte, et jamais moins bon.
"""

from __future__ import annotations

import numpy as np


# --------------------------------------------------------------------------- #
# Statistiques suffisantes
# --------------------------------------------------------------------------- #
def sufficient_statistics(X, y) -> dict:
    """Résumé d'un jeu de données : ``n``, ``D'D``, ``D'y``, ``y'y``.

    C'est exactement ce que le navigateur transmet au serveur. Voir le README
    pour la limite de confidentialité que ces sommes comportent malgré tout.
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
    return (np.asarray(stats["dtd"], float), np.asarray(stats["dty"], float),
            float(stats["yty"]), int(stats["n"]))


def add(a: dict, b: dict) -> dict:
    """Somme de deux résumés — l'opération centrale de l'agrégation fédérée."""
    return {
        "n": int(a["n"]) + int(b["n"]),
        "dtd": (np.asarray(a["dtd"], float)
                + np.asarray(b["dtd"], float)).tolist(),
        "dty": (np.asarray(a["dty"], float)
                + np.asarray(b["dty"], float)).tolist(),
        "yty": float(a["yty"]) + float(b["yty"]),
    }


# --------------------------------------------------------------------------- #
# Résolution
# --------------------------------------------------------------------------- #
def _solve(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Résout ``A x = b``, où ``A`` est une matrice de Gram éventuellement
    singulière.

    ``lstsq`` et non ``solve``, pour deux raisons. D'abord la robustesse : si un
    contributeur garde une variable constante dans son plan d'expériences (une
    seule vitesse de coupe, par exemple), ``A`` est singulière et ``solve``
    lèverait une exception, là où la solution de norme minimale reste
    exploitable. Ensuite la précision : passer par les équations normales élève
    le conditionnement au carré, et sur des unités physiques aussi
    déséquilibrées que les nôtres — ``h`` autour de 0.17 face à ``Vc`` autour de
    40, soit six ordres de grandeur sur la diagonale de ``D'D`` — cela compte.
    La décomposition en valeurs singulières sur laquelle repose ``lstsq`` absorbe
    ce mauvais conditionnement : l'ajustement sur les sommes rejoint celui sur
    données réunies à 1e-13 près, y compris à cond(D'D) ≈ 8e6.

    Un préconditionnement de Jacobi a été essayé ici et ne change rien (1e-11 sur
    la perte) : la SVD fait déjà le travail. Inutile de compliquer.
    """
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    return x


def solve_ols(stats: dict) -> np.ndarray:
    """Moindres carrés : ``theta = (D'D)^-1 D'y``."""
    dtd, dty, _, _ = parts(stats)
    return _solve(dtd, dty)


def solve_piml(stats: dict, lam: float, penalised_signs,
               max_iter: int = 100) -> np.ndarray:
    """PIML par ensemble actif : ``MSE + lam * somme(max(0, s_j c_j)^2)``.

    À ensemble de violations ``A`` fixé, annuler le gradient donne

        (D'D + n * lam * P_A) theta = D'y      avec P_A = diag(0, 1_A)

    L'ordonnée à l'origine n'est jamais pénalisée : elle ne porte aucun sens
    physique de variation. On résout, on recalcule ``A``, et on s'arrête dès
    qu'il ne bouge plus.
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


def loss_piml(stats: dict, theta: np.ndarray, lam: float,
              penalised_signs) -> float:
    """Valeur de la perte PIML — sert aux contrôles de non-régression."""
    signs = np.asarray(penalised_signs, float)
    viol = np.maximum(0.0, signs * theta[1:]) ** 2
    return sse(stats, theta) / int(stats["n"]) + lam * float(np.sum(viol))


# --------------------------------------------------------------------------- #
# Scores calculables sans les données
# --------------------------------------------------------------------------- #
def sse(stats: dict, theta: np.ndarray) -> float:
    dtd, dty, yty, _ = parts(stats)
    return float(yty - 2.0 * theta @ dty + theta @ dtd @ theta)


def train_metrics(stats: dict, theta: np.ndarray) -> dict:
    """R² et RMSE d'apprentissage.

    ``SST = y'y - n * ybar^2`` où ``ybar = (D'y)[0] / n``, puisque la première
    colonne de ``D`` ne contient que des 1.
    """
    _, dty, yty, n = parts(stats)
    ybar = float(dty[0]) / n
    residual = sse(stats, theta)
    total = yty - n * ybar ** 2
    return {
        "R2": float(1.0 - residual / total) if total > 0 else float("nan"),
        "RMSE": float(np.sqrt(max(residual, 0.0) / n)),
        "n": n,
    }


# --------------------------------------------------------------------------- #
# Centrage-réduction, également reconstitué depuis les sommes
# --------------------------------------------------------------------------- #
def pooled_scaler(stats: dict) -> tuple[np.ndarray, np.ndarray]:
    """Moyenne et écart-type des variables, retrouvés depuis ``D'D``.

    ``D'D[0, 1:]`` est la somme de chaque variable et ``diag(D'D)[1:]`` la somme
    de ses carrés : de quoi reconstituer le centrage-réduction des données
    réunies sans y avoir accès.
    """
    dtd, _, _, n = parts(stats)
    total = dtd[0, 1:]
    squares = np.diag(dtd)[1:]
    mean = total / n
    var = np.maximum(squares / n - mean ** 2, 0.0)
    std = np.sqrt(var)
    std[std == 0] = 1.0
    return mean, std


def to_standardised(stats: dict, mean: np.ndarray, std: np.ndarray) -> dict:
    """Réexprime les sommes dans l'espace centré-réduit.

    Avec ``Z = (X - m) / s``, on a ``D_z = D_x A`` pour la matrice affine ``A``
    ci-dessous, donc ``D_z'D_z = A'(D_x'D_x)A`` et ``D_z'y = A'(D_x'y)``. Le
    modèle linéaire de l'article vit dans cet espace : il faut pouvoir y
    transporter les sommes.
    """
    dtd, dty, yty, n = parts(stats)
    p = len(mean)
    A = np.zeros((p + 1, p + 1))
    A[0, 0] = 1.0
    for j in range(p):
        A[0, j + 1] = -mean[j] / std[j]
        A[j + 1, j + 1] = 1.0 / std[j]
    return {"n": n, "dtd": (A.T @ dtd @ A).tolist(),
            "dty": (A.T @ dty).tolist(), "yty": yty}
