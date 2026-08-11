/* Les moteurs du navigateur donnent-ils les mêmes chiffres que le Python ?
 *
 * C'est la condition pour qu'un score affiché sur le site soit comparable à un
 * score publié dans l'article. Le contrôle compare les coefficients, les scores
 * de validation croisée et la lecture des fichiers CSV.
 *
 *   node tests/check_engines.mjs <reference.json> [dossier-magasin]
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const web = (f) =>
  `file:///${path.join(ROOT, "web", "js", f).replace(/\\/g, "/")}`;

const referencePath = process.argv[2];
if (!referencePath) {
  console.error("usage : node tests/check_engines.mjs <reference.json> [magasin]");
  process.exit(2);
}
const store = process.argv[3] ?? path.join(ROOT, "server", "store");

const { applyScaler, fitOLS, fitPIML, fitScaler, looPredictions, predict,
        sufficientStatistics } = await import(web("models.js"));
const { metrics } = await import(web("score.js"));
const { buildMatrix, guessFeatureMapping, guessTargetColumns,
        parseDelimited } = await import(web("parse.js"));

const model = JSON.parse(
  readFileSync(path.join(store, "models", "model_v1.json"), "utf-8"));
const reference = JSON.parse(readFileSync(referencePath, "utf-8"));
const X = reference.X;
const signs = model.features.map((f) => model.penalised_sign[f]);

let failures = 0;
const check = (label, got, want, tol) => {
  const delta = Math.abs(got - want);
  const ok = delta <= tol;
  if (!ok) failures++;
  console.log(`${ok ? "OK  " : "FAIL"}  ${label.padEnd(38)} `
    + `js=${got.toFixed(6).padStart(14)}  py=${want.toFixed(6).padStart(14)}  `
    + `d=${delta.toExponential(2)}`);
};
const ok = (label, condition) => {
  if (!condition) failures++;
  console.log(`${condition ? "OK  " : "FAIL"}  ${label}`);
};

for (const target of Object.keys(model.targets)) {
  const y = reference[target];
  const tm = model.targets[target];
  console.log(`\n=== ${target} ===`);

  const scaler = fitScaler(X);
  scaler.mean.forEach((m, j) =>
    check(`scaler.mean[${model.features[j]}]`, m, tm.scaler.mean[j], 1e-9));
  scaler.std.forEach((s, j) =>
    check(`scaler.std[${model.features[j]}]`, s, tm.scaler.std[j], 1e-9));

  const linear = fitOLS(applyScaler(X, scaler), y);
  check("linear.intercept", linear.theta[0], tm.engines.linear.intercept, 1e-6);
  linear.theta.slice(1).forEach((c, j) =>
    check(`linear.coef[${model.features[j]}]`, c,
          tm.engines.linear.coef[j], 1e-6));

  // Tolérance plus large sur PIML : l'ensemble actif du JavaScript et celui du
  // Python convergent vers le même optimum, mais par des chemins différents sur
  // une vallée de perte très plate (le coefficient de h est mal déterminé, h ne
  // variant que de 0.15 à 0.20).
  const lam = tm.engines.piml.lambda;
  const piml = fitPIML(X, y, lam, signs);
  check("piml.intercept", piml.theta[0], tm.engines.piml.intercept, 5e-3);
  piml.theta.slice(1).forEach((c, j) =>
    check(`piml.coef[${model.features[j]}]`, c, tm.engines.piml.coef[j], 5e-4));

  const looLinear = looPredictions(applyScaler(X, scaler), y,
                                   (Xt, yt) => fitOLS(Xt, yt));
  check("linear LOO R2", metrics(y, looLinear).R2,
        tm.engines.linear.loo.R2, 1e-6);
  check("linear LOO RMSE", metrics(y, looLinear).RMSE,
        tm.engines.linear.loo.RMSE, 1e-4);

  const looPiml = looPredictions(X, y, (Xt, yt) => fitPIML(Xt, yt, lam, signs));
  check("piml LOO R2", metrics(y, looPiml).R2, tm.engines.piml.loo.R2, 1e-4);
  check("piml LOO RMSE", metrics(y, looPiml).RMSE,
        tm.engines.piml.loo.RMSE, 1e-3);

  // Appliquer le modèle publié à ses propres données d'entraînement doit rendre
  // le R² d'apprentissage publié : c'est le contrôle du score de transfert.
  const published = [tm.engines.linear.intercept, ...tm.engines.linear.coef];
  check("transfert = R2 d'apprentissage publié",
        metrics(y, predict(applyScaler(X, tm.scaler), published)).R2,
        tm.engines.linear.train.R2, 1e-6);

  const stats = sufficientStatistics(X, y);
  check("stats.dtd[0][0] vaut n", stats.dtd[0][0], stats.n, 1e-9);
}

/* --- lecture des fichiers de mesures ------------------------------------- */
console.log("\n=== lecture du gabarit CSV ===");
const csvPath = path.join(ROOT, "web", "template", "titanium_template.csv");
const csv = readFileSync(csvPath, "utf-8");
const table = parseDelimited(csv);
console.log(`colonnes : ${table.columns.join(" | ")}`);

const mapping = guessFeatureMapping(model.features, table.columns, table.rows);
for (const feature of model.features) {
  ok(`${feature.padEnd(8)} -> ${mapping[feature] || "(non trouvé)"}`,
     Boolean(mapping[feature]));
}
const targets = guessTargetColumns(table.columns, table.rows);
ok(`cibles proposées : ${targets.join(", ") || "(aucune)"}`, targets.length > 0);

const built = buildMatrix(table.rows, model.features.map((f) => mapping[f]),
                          targets[0]);
ok(`${built.X.length} ligne(s) exploitable(s), ${built.dropped} écartée(s)`,
   built.X.length === table.rows.length && built.dropped === 0);

// Export Excel européen : point-virgule et virgule décimale. C'est le cas qui
// casse le plus souvent en pratique, et silencieusement — le fichier se lit,
// mais toutes les mesures arrivent en texte.
const european = csv.replace(/,/g, ";").replace(/(\d)\.(\d)/g, "$1,$2");
const euroTable = parseDelimited(european);
ok(`export Excel européen : séparateur ${JSON.stringify(euroTable.sep)}, `
   + `décimale ${JSON.stringify(euroTable.decimal)}, `
   + `${euroTable.columns.length} colonnes`,
   euroTable.sep === ";" && euroTable.decimal === ","
   && euroTable.columns.length === table.columns.length);

// Lignes de titre avant l'en-tête : fréquent sur les classeurs de laboratoire.
const titled = parseDelimited(`Campagne contraintes 2026\nLabo XYZ\n${csv}`);
ok(`lignes de titre : en-tête détecté ligne ${titled.headerRow + 1}, `
   + `${titled.columns.length} colonnes`,
   titled.headerRow === 2 && titled.columns.length === table.columns.length);

// Colonnes grecques du fichier de l'étude : sans la table de translittération,
// « γ (°) » devient méconnaissable et la variable disparaît des propositions.
const greek = parseDelimited(
  "γ (°),rβ (µm),Vc (m/min),h (mm),σ résiduelle L (MPa)\n"
  + "0,20,30,0.15,-400\n0,20,50,0.15,-350\n");
const greekMapping = guessFeatureMapping(model.features, greek.columns, greek.rows);
ok(`noms grecs : ${model.features.map((f) => greekMapping[f] || "?").join(", ")}`,
   model.features.every((f) => Boolean(greekMapping[f])));

console.log(`\n${failures === 0 ? "TOUT CONCORDE" : `${failures} ÉCART(S)`}`);
process.exit(failures === 0 ? 0 : 1);
