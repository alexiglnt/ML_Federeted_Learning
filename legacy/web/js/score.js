/* Les deux scores demandés, et la distinction entre eux.
 *
 * Le professeur a demandé les deux, et ils ne mesurent pas la même chose :
 *
 *   * TRANSFERT — le modèle global est appliqué tel quel aux mesures du
 *     collègue, sans réajustement. Répond à : « notre modèle publié marche-t-il
 *     ailleurs que chez nous ? » C'est une validation externe de l'étude.
 *
 *   * RÉAJUSTEMENT — le modèle est réajusté sur les seules données du collègue,
 *     et noté en validation croisée. Répond à : « ses données sont-elles
 *     prédictibles ? » Cela ne dit rien sur la qualité de notre modèle.
 *
 * Les deux ensemble se lisent : transfert faible et réajustement fort signifie
 * des données propres mais un modèle qui ne se transporte pas — l'information
 * la plus utile que le site puisse produire.
 */

import {
  applyScaler, fitOLS, fitPIML, fitScaler, looPredictions, predict,
} from "./models.js";

/** R², RMSE, MAE. Même formule que côté Python, pour que les chiffres se comparent. */
export function metrics(yTrue, yPred) {
  const n = yTrue.length;
  const mean = yTrue.reduce((a, b) => a + b, 0) / n;
  let ssRes = 0;
  let ssTot = 0;
  let absSum = 0;
  for (let i = 0; i < n; i++) {
    const err = yTrue[i] - yPred[i];
    ssRes += err * err;
    ssTot += (yTrue[i] - mean) ** 2;
    absSum += Math.abs(err);
  }
  return {
    R2: ssTot > 0 ? 1 - ssRes / ssTot : NaN,
    RMSE: Math.sqrt(ssRes / n),
    MAE: absSum / n,
    n,
  };
}

/**
 * Score de transfert : le modèle global, appliqué sans rien réajuster.
 *
 * Le moteur linéaire vit dans l'espace centré-réduit du jeu d'origine ; il faut
 * donc appliquer LE scaler publié, pas celui des données du collègue.
 * Recalculer le centrage sur ses propres données changerait le modèle et ce ne
 * serait plus un test de transfert.
 */
export function transferScores(X, y, targetModel) {
  const out = {};
  for (const [name, engine] of Object.entries(targetModel.engines)) {
    const theta = [engine.intercept, ...engine.coef];
    const Xuse = engine.space === "standardised"
      ? applyScaler(X, targetModel.scaler)
      : X;
    out[name] = metrics(y, predict(Xuse, theta));
  }
  return out;
}

/**
 * Score après réajustement local, en validation croisée.
 *
 * Le scaler est réajusté À L'INTÉRIEUR de chaque pli. Le faire une fois pour
 * toutes sur l'ensemble des points laisserait fuiter la moyenne et l'écart-type
 * du point de test dans l'entraînement, et gonflerait le score.
 */
export function refitScores(X, y, model) {
  const signs = model.features.map((f) => model.penalised_sign[f] ?? 0);
  const lam = 5.0;

  const linearFitter = (Xtr, ytr) => {
    const scaler = fitScaler(Xtr);
    const fit = fitOLS(applyScaler(Xtr, scaler), ytr);
    // Les coefficients sont ramenés dans l'espace brut, pour que le modèle
    // appris dans un pli puisse s'appliquer au point laissé de côté sans
    // transporter le scaler avec lui.
    if (!fit.theta) return fit;
    const raw = [fit.theta[0]];
    for (let j = 0; j < scaler.mean.length; j++) {
      raw.push(fit.theta[j + 1] / scaler.std[j]);
      raw[0] -= (fit.theta[j + 1] * scaler.mean[j]) / scaler.std[j];
    }
    return { theta: raw, ridge: fit.ridge };
  };
  const pimlFitter = (Xtr, ytr) => fitPIML(Xtr, ytr, lam, signs);

  const scaler = fitScaler(X);
  const linearFull = fitOLS(applyScaler(X, scaler), y);
  const pimlFull = pimlFitter(X, y);

  return {
    lambda: lam,
    scaler,
    engines: {
      linear: {
        space: "standardised",
        intercept: linearFull.theta?.[0] ?? NaN,
        coef: linearFull.theta?.slice(1) ?? [],
        ridge: linearFull.ridge,
        train: metrics(y, predict(applyScaler(X, scaler), linearFull.theta ?? [])),
        loo: metrics(y, looPredictions(X, y, linearFitter)),
      },
      piml: {
        space: "raw",
        lambda: lam,
        intercept: pimlFull.theta?.[0] ?? NaN,
        coef: pimlFull.theta?.slice(1) ?? [],
        ridge: pimlFull.ridge,
        train: metrics(y, predict(X, pimlFull.theta ?? [])),
        loo: metrics(y, looPredictions(X, y, pimlFitter)),
      },
    },
  };
}

/** Lecture en une phrase du couple (transfert, réajustement). */
export function interpret(transferR2, refitR2) {
  const good = (r) => r >= 0.5;
  const poor = (r) => r < 0;
  if (good(transferR2) && good(refitR2)) {
    return "Le modèle global se transfère à vos mesures : il les prédit sans " +
      "avoir été réajusté. C'est le meilleur cas de figure, et votre jeu " +
      "confirme le modèle publié.";
  }
  if (!good(transferR2) && good(refitR2)) {
    return "Vos mesures sont cohérentes entre elles — un modèle ajusté dessus " +
      "les prédit bien — mais le modèle global ne s'y transfère pas. C'est " +
      "l'information la plus utile que vous puissiez nous transmettre : elle " +
      "indique un régime que le modèle publié ne couvre pas.";
  }
  if (poor(refitR2)) {
    return "Même réajusté sur vos seules données, le modèle ne les prédit pas. " +
      "Cela vient en général d'un domaine expérimental trop resserré, d'une " +
      "dispersion de mesure importante, ou d'une variable déterminante " +
      "absente du tableau — pas nécessairement d'un problème de modèle.";
  }
  return "Résultat intermédiaire : le modèle capte une partie de la tendance " +
    "sans être fiable point par point. À interpréter avec le nombre de " +
    "conditions et l'étendue du domaine exploré.";
}
