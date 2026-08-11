/* Les deux moteurs, en version navigateur.
 *
 * Ce fichier est le cœur du dispositif : c'est parce que l'ajustement tourne
 * ICI, sur la machine du collègue, que ses mesures n'ont pas à quitter son
 * poste. Les résultats sont volontairement identiques à ceux du code Python de
 * l'étude (tools/fit_pretrained.py), afin qu'un score obtenu sur le site soit
 * comparable à un score publié.
 */

import { designMatrix, gram, matTvec, solveRegularised, dot } from "./linalg.js";

/** Moyenne et écart-type par colonne (écart-type nul ramené à 1). */
export function fitScaler(X) {
  const n = X.length;
  const p = X[0].length;
  const mean = new Float64Array(p);
  const std = new Float64Array(p);
  for (const row of X) for (let j = 0; j < p; j++) mean[j] += row[j] / n;
  for (const row of X) {
    for (let j = 0; j < p; j++) std[j] += (row[j] - mean[j]) ** 2 / n;
  }
  for (let j = 0; j < p; j++) std[j] = Math.sqrt(std[j]) || 1;
  return { mean: Array.from(mean), std: Array.from(std) };
}

export function applyScaler(X, scaler) {
  return X.map((row) => row.map((v, j) => (v - scaler.mean[j]) / scaler.std[j]));
}

/** Prédiction d'un modèle affine theta = [ordonnée, coefs...]. */
export function predict(X, theta) {
  return X.map((row) => {
    let s = theta[0];
    for (let j = 0; j < row.length; j++) s += theta[j + 1] * row[j];
    return s;
  });
}

/** Moindres carrés ordinaires. Renvoie { theta, ridge }. */
export function fitOLS(X, y) {
  const D = designMatrix(X);
  const { x, ridge } = solveRegularised(gram(D), matTvec(D, y));
  return { theta: x ? Array.from(x) : null, ridge };
}

/**
 * PIML — linéaire pénalisé quand un coefficient contredit la physique.
 *
 * Perte identique à celle de l'étude :
 *     MSE + lam * somme( max(0, signe_interdit_j * c_j)^2 )
 *
 * L'étude minimise cette perte par L-BFGS-B. Ici on exploite le fait qu'elle
 * est convexe et quadratique par morceaux : à ensemble de violations fixé, le
 * minimum a une forme close. Pour A l'ensemble des coefficients en infraction,
 *
 *     (D'D + n * lam * P_A) theta = D'y      avec P_A = diag(0, 1_A)
 *
 * On itère : résoudre, recalculer A, recommencer jusqu'à ce que A ne bouge
 * plus. La vérification faite côté Python donne le même optimum que L-BFGS-B à
 * 1e-9 près sur la perte, pour tous les lambda du balayage — sans embarquer
 * d'optimiseur dans la page.
 */
export function fitPIML(X, y, lam, penalisedSigns, maxIter = 100) {
  const n = y.length;
  const p = X[0].length;
  const D = designMatrix(X);
  const dtd = gram(D);
  const dty = matTvec(D, y);

  let { x, ridge } = solveRegularised(dtd, dty);
  if (!x) return { theta: null, ridge: null, iterations: 0 };
  let theta = Array.from(x);
  let active = null;

  let iterations = 0;
  for (; iterations < maxIter; iterations++) {
    const next = new Array(p);
    for (let j = 0; j < p; j++) next[j] = penalisedSigns[j] * theta[j + 1] > 0;
    if (active && next.every((v, j) => v === active[j])) break;
    active = next;

    const A = dtd.map((row) => Array.from(row));
    for (let j = 0; j < p; j++) {
      if (active[j]) A[j + 1][j + 1] += n * lam;
    }
    const step = solveRegularised(A, dty);
    if (!step.x) break;
    theta = Array.from(step.x);
    ridge = Math.max(ridge ?? 0, step.ridge ?? 0);
  }
  return { theta, ridge, iterations };
}

/**
 * Prédictions en validation croisée « un point de côté ».
 *
 * Sur les effectifs dont il est question ici — sept conditions dans l'étude,
 * quelques dizaines chez un collègue — c'est le seul score qui veuille dire
 * quelque chose. Le R² d'apprentissage d'un modèle à cinq paramètres sur sept
 * points est un artefact, et l'afficher seul induirait tout le monde en erreur.
 */
export function looPredictions(X, y, fitter) {
  const n = y.length;
  const out = new Float64Array(n);
  for (let k = 0; k < n; k++) {
    const Xtr = [];
    const ytr = [];
    for (let i = 0; i < n; i++) {
      if (i === k) continue;
      Xtr.push(X[i]);
      ytr.push(y[i]);
    }
    const { theta } = fitter(Xtr, ytr);
    out[k] = theta ? predict([X[k]], theta)[0] : NaN;
  }
  return Array.from(out);
}

/**
 * Statistiques suffisantes — la « mise à jour de modèle » envoyée au serveur.
 *
 * Avec D = [1, X], la somme des carrés des résidus vaut
 *     SSE(theta) = y'y - 2 theta'(D'y) + theta'(D'D) theta
 * donc D'D, D'y, y'y et n suffisent à refaire l'ajustement sur les données
 * réunies de tous les laboratoires, au chiffre près, sans qu'aucune mesure ne
 * circule. C'est ce qui rend l'agrégation exacte au lieu d'une moyenne de
 * coefficients à la FedAvg.
 */
export function sufficientStatistics(X, y) {
  const D = designMatrix(X);
  return {
    n: y.length,
    dtd: gram(D).map((row) => Array.from(row)),
    dty: Array.from(matTvec(D, y)),
    yty: dot(y, y),
  };
}
