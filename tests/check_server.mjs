/* Le serveur tient-il ses promesses ?
 *
 * Le contrôle joue le rôle d'un collègue : il calcule ses scores avec les MÊMES
 * modules JavaScript que la page, assemble sa contribution, et l'envoie. Puis il
 * vérifie les deux choses qui comptent :
 *
 *   1. aucune mesure individuelle ne figure dans le corps de l'envoi ;
 *   2. le serveur refuse ce qu'il doit refuser — clé absente ou fausse, sommes
 *      incohérentes ou fabriquées, trop peu de lignes, métadonnées manquantes.
 *
 *   node tests/check_server.mjs <fixture.json> [url-de-base]
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const web = (f) =>
  `file:///${path.join(ROOT, "web", "js", f).replace(/\\/g, "/")}`;

const fixturePath = process.argv[2];
if (!fixturePath) {
  console.error("usage : node tests/check_server.mjs <fixture.json> [url]");
  process.exit(2);
}
const BASE = process.argv[3] ?? "http://127.0.0.1:8077";
const API_KEY = process.env.DEAM_FL_API_KEY ?? "test-key-123";
const ADMIN_KEY = process.env.DEAM_FL_ADMIN_KEY ?? "admin-456";

const { sufficientStatistics } = await import(web("models.js"));
const { refitScores, transferScores } = await import(web("score.js"));
const { buildContribution } = await import(web("api.js"));

const model = await (await fetch(`${BASE}/api/model`)).json();
const fixture = JSON.parse(readFileSync(fixturePath, "utf-8"));
if (fixture.from_model_version !== model.version) {
  console.error(`la fixture vient du modèle v${fixture.from_model_version} `
    + `mais le serveur sert v${model.version} — relancer gen_fixture.mjs`);
  process.exit(2);
}

const { X, y, target } = fixture;
const tm = model.targets[target];
console.log(`collègue fictif : ${X.length} conditions, cible ${target}`);

/* --- ce que la page calcule ---------------------------------------------- */
const transfer = transferScores(X, y, tm);
const refit = refitScores(X, y, model);
console.log(`  transfert  : linéaire R² ${transfer.linear.R2.toFixed(3)}   `
  + `PIML R² ${transfer.piml.R2.toFixed(3)}`);
console.log(`  réajusté   : linéaire R²_LOO ${refit.engines.linear.loo.R2.toFixed(3)}   `
  + `PIML R²_LOO ${refit.engines.piml.loo.R2.toFixed(3)}`);

const stats = sufficientStatistics(X, y);
const ranges = {};
model.features.forEach((f, j) => {
  const column = X.map((row) => row[j]);
  ranges[f] = [Math.min(...column), Math.max(...column)];
});

const payload = buildContribution({
  model, target, features: model.features,
  contributor: { name: "A. Colleague", lab: "Laboratoire fictif", email: null },
  dataset: {
    n_rows: stats.n, material: "Ti-6Al-4V", process: "orthogonal turning",
    coolant: "dry", measurement_method: "XRD", feature_ranges: ranges,
    notes: "Jeu de contrôle synthétique — pas des mesures réelles.",
  },
  stats,
  localFit: {
    linear: { space: "standardised", intercept: refit.engines.linear.intercept,
              coef: refit.engines.linear.coef, train: refit.engines.linear.train,
              loo: refit.engines.linear.loo },
    piml: { space: "raw", lambda: refit.engines.piml.lambda,
            intercept: refit.engines.piml.intercept,
            coef: refit.engines.piml.coef, train: refit.engines.piml.train,
            loo: refit.engines.piml.loo },
  },
  scores: {
    transfer_linear: transfer.linear, transfer_piml: transfer.piml,
    refit_linear_loo: refit.engines.linear.loo,
    refit_piml_loo: refit.engines.piml.loo,
  },
});
const wire = JSON.stringify(payload);

let failures = 0;
const expect = (label, got, want) => {
  const ok = got === want;
  if (!ok) failures++;
  console.log(`${ok ? "OK  " : "FAIL"}  ${label.padEnd(42)} `
    + `HTTP ${got} (attendu ${want})`);
};

/* --- 1. aucune mesure dans l'envoi --------------------------------------- */
let leaks = 0;
for (const value of y) if (wire.includes(value.toFixed(6))) leaks++;
for (const row of X) {
  for (const value of row) {
    // Les bornes min/max sont transmises volontairement — elles disent si la
    // contribution élargit le domaine de validité. Seules les valeurs
    // intérieures ne doivent jamais apparaître.
    const isBound = Object.values(ranges)
      .some(([lo, hi]) => value === lo || value === hi);
    if (!isBound && wire.includes(value.toFixed(6))) leaks++;
  }
}
if (leaks) failures++;
console.log(`${leaks === 0 ? "OK  " : "FAIL"}  aucune mesure individuelle dans `
  + `l'envoi (${leaks} fuite(s))`);

/* --- 2. contrôle d'accès ------------------------------------------------- */
const post = async (key, body = wire) => (await fetch(`${BASE}/api/contribute`, {
  method: "POST",
  headers: { "Content-Type": "application/json", ...(key ? { "X-API-Key": key } : {}) },
  body,
})).status;

expect("sans clé -> refus", await post(null), 401);
expect("mauvaise clé -> refus", await post("wrong"), 401);

const accepted = await fetch(`${BASE}/api/contribute`, {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
  body: wire,
});
expect("bonne clé -> accepté", accepted.status, 202);
const receipt = await accepted.json().catch(() => ({}));
console.log(`      reçu ${receipt.id}, n=${receipt.n_rows}`);

/* --- 3. envois incohérents ou fabriqués ---------------------------------- */
const mutated = (fn) => {
  const copy = JSON.parse(wire);
  fn(copy);
  return JSON.stringify(copy);
};

expect("variables permutées -> refus",
  await post(API_KEY, mutated((p) => { p.features = [...p.features].reverse(); })), 422);
expect("dtd[0][0] différent de n -> refus",
  await post(API_KEY, mutated((p) => { p.sufficient_statistics.dtd[0][0] = 999; })), 422);
expect("dtd non symétrique -> refus",
  await post(API_KEY, mutated((p) => { p.sufficient_statistics.dtd[0][1] += 1234; })), 422);
expect("dtd non semi-définie positive -> refus",
  await post(API_KEY, mutated((p) => {
    const d = p.sufficient_statistics.dtd;
    for (let i = 1; i < d.length; i++) d[i][i] = -Math.abs(d[i][i]);
  })), 422);
expect("valeurs non finies -> refus",
  await post(API_KEY, mutated((p) => { p.sufficient_statistics.dty[1] = null; })), 422);
expect("grandeur inconnue -> refus",
  await post(API_KEY, mutated((p) => { p.target = "SRS_X"; })), 422);
expect("trop peu de lignes -> refus",
  await post(API_KEY, mutated((p) => {
    p.dataset.n_rows = 2;
    p.sufficient_statistics.n = 2;
  })), 422);
expect("n annoncé incohérent -> refus",
  await post(API_KEY, mutated((p) => { p.dataset.n_rows = 99; })), 422);
expect("méthode de mesure absente -> refus",
  await post(API_KEY, mutated((p) => { delete p.dataset.measurement_method; })), 422);
expect("méthode de mesure inventée -> refus",
  await post(API_KEY, mutated((p) => { p.dataset.measurement_method = "guesswork"; })), 422);
expect("laboratoire vide -> refus",
  await post(API_KEY, mutated((p) => { p.contributor.lab = ""; })), 422);

/* --- 4. la file d'attente est réservée ----------------------------------- */
expect("file sans clé admin -> refus", (await fetch(`${BASE}/api/queue`)).status, 401);
const queue = await fetch(`${BASE}/api/queue`,
                          { headers: { "X-Admin-Key": ADMIN_KEY } });
expect("file avec clé admin -> ok", queue.status, 200);
const body = await queue.json();
const single = body.count === 1;
if (!single) failures++;
console.log(`${single ? "OK  " : "FAIL"}  une seule contribution en attente `
  + `(${body.count}) — les envois refusés n'ont rien laissé`);

/* --- 5. la file ne doit pas exposer les sommes --------------------------- */
const queueWire = JSON.stringify(body);
const exposesStats = queueWire.includes("dtd") || queueWire.includes("yty");
if (exposesStats) failures++;
console.log(`${exposesStats ? "FAIL" : "OK  "}  la file d'attente ne renvoie `
  + `que les métadonnées, pas les sommes`);

console.log(`\n${failures === 0 ? "SERVEUR CONFORME" : `${failures} ÉCART(S)`}`);
process.exit(failures === 0 ? 0 : 1);
