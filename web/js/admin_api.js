/* Les appels réseau réservés à l'administration : file d'attente et
 * agrégation. Séparés de api.js à dessein — api.js documente les TROIS seuls
 * appels que fait la page publique à un collègue qui vérifie ce qui part de
 * son navigateur ; mélanger les routes admin ici casserait cette promesse
 * lisible en une minute.
 */
const BASE = "/api";

async function authedJSON(path, adminKey, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      "X-Admin-Key": adminKey,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => `${(d.loc ?? []).join(".")} : ${d.msg}`).join("\n")
      : (detail || `${response.status} ${response.statusText}`);
    throw new Error(message);
  }
  return body;
}

export const fetchQueue = (adminKey) => authedJSON("/queue", adminKey);

export const runAggregation = (adminKey, { exclude = [], dryRun = false } = {}) =>
  authedJSON("/aggregate", adminKey, {
    method: "POST",
    body: JSON.stringify({ exclude, dry_run: dryRun }),
  });

export const rollbackTo = (adminKey, toVersion) =>
  authedJSON("/rollback", adminKey, {
    method: "POST",
    body: JSON.stringify({ to_version: toVersion }),
  });

export async function fetchHistory() {
  const response = await fetch(`${BASE}/history`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}
