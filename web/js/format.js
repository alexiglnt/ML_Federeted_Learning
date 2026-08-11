/* Le serveur horodate tout en UTC (voir server/app.py, server/aggregate.py) —
 * c'est le seul choix sensé côté serveur, qui ne connaît pas le fuseau du
 * visiteur. Découper la chaîne ISO telle quelle affichait donc l'heure UTC
 * brute, plusieurs heures en avance pour des collègues aux États-Unis. Ces
 * deux fonctions convertissent dans le fuseau ET le format (12h/24h) du
 * navigateur qui affiche — jamais un fuseau ou un format choisi ici.
 */
export function formatDateTime(isoUtc) {
  const date = new Date(isoUtc ?? "");
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export function formatDate(isoUtc) {
  const date = new Date(isoUtc ?? "");
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit",
  });
}
