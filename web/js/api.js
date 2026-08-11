/* Les seuls échanges réseau de la page.
 *
 * Tenir tous les appels dans un fichier court est délibéré : un collègue
 * méfiant — et il a raison de l'être — doit pouvoir vérifier en une minute que
 * rien d'autre ne sort. Il n'y a que trois appels : télécharger le modèle,
 * lire l'historique, envoyer une contribution.
 *
 * Aucune mesure ne figure dans le corps du POST : voir buildContribution, qui
 * énumère explicitement tout ce qui est transmis.
 */

const BASE = "/api";

async function getJSON(path) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}${detail ? ` — ${detail}` : ""}`);
  }
  return response.json();
}

export const fetchModel = () => getJSON("/model");
export const fetchHistory = () => getJSON("/history");
export const fetchStatus = () => getJSON("/status");

/**
 * Assemble la contribution. Tout ce qui part est écrit ici, en clair :
 *
 *   * l'identité déclarée par le contributeur et les métadonnées du jeu
 *     (matière, méthode de mesure, nombre de lignes, étendue de chaque
 *     variable) ;
 *   * les statistiques suffisantes — D'D, D'y, y'y, n — qui permettent de
 *     réajuster le modèle sur les données réunies sans les transporter ;
 *   * les coefficients obtenus localement et les deux scores.
 *
 * Il n'y a aucun tableau de mesures. L'étendue des variables est le seul
 * élément qui décrit les entrées, et elle est nécessaire pour savoir si une
 * contribution élargit le domaine de validité du modèle ou le confirme.
 */
export function buildContribution({ model, target, features, contributor,
                                    dataset, stats, localFit, scores }) {
  return {
    schema: "deam-fl-contribution/1",
    model_version: model.version,
    target,
    features,
    contributor,
    dataset,
    sufficient_statistics: stats,
    local_fit: localFit,
    scores,
  };
}

export async function postContribution(payload, apiKey) {
  const response = await fetch(`${BASE}/contribute`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    // FastAPI renvoie le motif dans `detail` ; pour une erreur de validation
    // c'est une liste d'objets, qu'il faut aplatir pour l'afficher.
    const detail = body.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => `${(d.loc ?? []).join(".")} : ${d.msg}`).join("\n")
      : (detail || `${response.status} ${response.statusText}`);
    throw new Error(message);
  }
  return body;
}
