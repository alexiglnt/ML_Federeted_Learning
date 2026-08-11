/* Fabrique le jeu de données d'un « collègue » fictif, une fois pour toutes.
 *
 * Douze conditions tirées dans le domaine du plan d'expériences, avec une
 * réponse proche du modèle PIML publié plus un bruit de mesure de 30 MPa. Cela
 * n'a aucune valeur scientifique : c'est un support de contrôle.
 *
 * Le jeu est écrit dans un fichier et relu par check_server.mjs comme par
 * check_aggregation.py. C'est indispensable : la première version de ces
 * contrôles régénérait les données de chaque côté, et comme la réponse dépend
 * des coefficients du modèle v1, la moindre évolution de celui-ci faisait
 * dériver les deux jeux. On croyait alors à une agrégation imprécise à 1e-5
 * alors que seul le jeu de contrôle avait bougé.
 *
 *   node tests/gen_fixture.mjs <fichier-sortie> [dossier-magasin]
 */
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = process.argv[2];
if (!out) {
  console.error("usage : node tests/gen_fixture.mjs <fichier-sortie> [magasin]");
  process.exit(2);
}
const store = process.argv[3] ?? path.join(ROOT, "server", "store");

const model = JSON.parse(
  readFileSync(path.join(store, "models", "model_v1.json"), "utf-8"));
const theta = [model.targets.SRS_L.engines.piml.intercept,
               ...model.targets.SRS_L.engines.piml.coef];

// Générateur congruentiel linéaire : reproductible, sans dépendance.
let seed = 20260806;
const rand = () => {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x7fffffff;
};
const gauss = () =>
  Math.sqrt(-2 * Math.log(rand() || 1e-9)) * Math.cos(2 * Math.PI * rand());

const BOUNDS = { gamma: [-6, 5], r_beta: [16, 30], Vc: [20, 60], h: [0.15, 0.20] };

const X = [];
const y = [];
for (let i = 0; i < 12; i++) {
  const row = model.features.map((f) => {
    const [lo, hi] = BOUNDS[f];
    return lo + rand() * (hi - lo);
  });
  let value = theta[0];
  row.forEach((v, j) => { value += theta[j + 1] * v; });
  X.push(row);
  y.push(value + 30 * gauss());
}

writeFileSync(out, JSON.stringify({
  X, y, target: "SRS_L", from_model_version: model.version,
}, null, 1));
console.log(`fixture : ${X.length} conditions (modèle v${model.version})`);
