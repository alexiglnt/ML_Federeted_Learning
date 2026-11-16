/* Page d'administration : file d'attente, aperçu et publication.
 *
 * Ne duplique aucun calcul : la prévisualisation et la publication passent
 * toutes les deux par POST /api/aggregate, qui appelle exactement
 * run_aggregation() — la même fonction que « python -m server.aggregate » en
 * ligne de commande (voir server/aggregate.py). Cette page n'est qu'une autre
 * façon de déclencher le même calcul, jamais une implémentation parallèle.
 */
import { fetchHistory, fetchQueue, rollbackTo, runAggregation } from "./admin_api.js";
import { formatDate, formatDateTime } from "./format.js";
import { wireThemeToggle } from "./theme.js";

const KEY_STORAGE = "deam-admin-key";

const state = {
  adminKey: sessionStorage.getItem(KEY_STORAGE) || "",
  queue: [],
};

const $ = (id) => document.getElementById(id);
const fmt = (v, digits = 3) => (Number.isFinite(v) ? v.toFixed(digits) : "—");

function show(id, visible = true) {
  $(id).hidden = !visible;
}

function report(id, level, html) {
  const box = $(id);
  box.className = `report ${level}`;
  box.innerHTML = html;
  box.hidden = false;
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------------------------------------------------------------- */
/* 1 — clé admin                                                          */
/* ---------------------------------------------------------------------- */
function wireAuth() {
  $("auth-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const key = $("admin-key").value.trim();
    if (!key) return;
    state.adminKey = key;
    sessionStorage.setItem(KEY_STORAGE, key);
    loadQueue();
  });

  $("forget-key-button").addEventListener("click", () => {
    state.adminKey = "";
    sessionStorage.removeItem(KEY_STORAGE);
    $("admin-key").value = "";
    show("step-queue", false);
    show("step-action", false);
    show("step-history", false);
    report("auth-report", "info", "<p>Key forgotten for this tab.</p>");
  });

  if (state.adminKey) {
    $("admin-key").value = state.adminKey;
    loadQueue();
  }
}

/* ---------------------------------------------------------------------- */
/* 2 — file d'attente                                                     */
/* ---------------------------------------------------------------------- */
async function loadQueue() {
  try {
    const { pending } = await fetchQueue(state.adminKey);
    state.queue = pending;
    show("auth-report", false);
    renderQueue();
    show("step-queue", true);
    show("step-action", true);
    await loadHistory();
  } catch (error) {
    report("auth-report", "error",
      `<strong>Could not load the queue.</strong><p>${escapeHtml(error.message)}</p>`);
    show("step-queue", false);
    show("step-action", false);
    show("step-history", false);
  }
}

function renderQueue() {
  if (!state.queue.length) {
    $("queue-wrap").innerHTML = `<p class="muted">Queue is empty.</p>`;
    return;
  }

  const rows = state.queue.map((item) => {
    const scores = Object.entries(item.scores ?? {})
      .filter(([k]) => k.endsWith("_loo") || k.startsWith("refit"))
      .map(([k, v]) => `${k.replace(/^refit_|_loo$/g, "")} R² ${fmt(v?.R2)}`)
      .join(" · ");
    return `<tr>
      <td><input type="checkbox" class="queue-check" data-id="${escapeHtml(item.id)}" checked
          aria-label="Include ${escapeHtml(item.id)} in the next aggregation"></td>
      <td><span class="tname">${escapeHtml(item.id)}</span></td>
      <td>${formatDateTime(item.received_utc)}</td>
      <td>${escapeHtml(item.target)}</td>
      <td>${item.dataset?.n_rows ?? "—"}</td>
      <td>${escapeHtml(item.dataset?.material ?? "—")}</td>
      <td>${escapeHtml(item.dataset?.measurement_method ?? "—")}</td>
      <td>${escapeHtml(item.contributor?.lab ?? "—")}
        <span class="muted">(${escapeHtml(item.contributor?.name ?? "—")})</span></td>
      <td class="muted">${scores || "—"}</td>
    </tr>`;
  }).join("");

  $("queue-wrap").innerHTML = `<div style="overflow-x:auto;">
    <table class="history queue-table">
      <thead><tr>
        <th>Include</th><th>ID</th><th>Received</th><th>Target</th><th>n</th>
        <th>Material</th><th>Method</th><th>Contributor</th><th>Local scores</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function excludedIds() {
  return Array.from(document.querySelectorAll(".queue-check"))
    .filter((box) => !box.checked)
    .map((box) => box.dataset.id);
}

/* ---------------------------------------------------------------------- */
/* 3 — aperçu / publication                                               */
/* ---------------------------------------------------------------------- */
function renderResult(result) {
  const level = result.to_version ? "ok" : "info";
  report("action-report", level, `<p><strong>${escapeHtml(result.message)}</strong></p>`);

  const used = (result.used ?? []).map((u) =>
    `<li>${escapeHtml(u.id)} — ${escapeHtml(u.lab)} (${escapeHtml(u.target)}, n=${u.n_rows})</li>`
  ).join("");
  const skipped = (result.skipped ?? []).map((s) =>
    `<li>${escapeHtml(s.id)} — ${escapeHtml(s.reason)}</li>`
  ).join("");
  const targets = Object.entries(result.targets ?? {}).map(([name, t]) => `
    <div class="score-line">
      <span class="engine">${escapeHtml(name)}</span>
      <span class="rmse">n=${t.n_train}</span>
      <span class="r2 ${t.linear_train_r2 >= 0.5 ? "good" : "mid"}">linear R² ${fmt(t.linear_train_r2)}</span>
      <span class="r2 ${t.piml_train_r2 >= 0.5 ? "good" : "mid"}">PIML R² ${fmt(t.piml_train_r2)}</span>
    </div>`).join("");

  $("action-detail").innerHTML = `
    ${targets ? `<div class="score-card" style="margin-top:1rem;">
      <h3>Pooled training scores${result.dry_run ? " (preview)" : ""}</h3>
      ${targets}
    </div>` : ""}
    ${used ? `<div style="margin-top:1rem;"><strong>Used</strong><ul>${used}</ul></div>` : ""}
    ${skipped ? `<div style="margin-top:1rem;"><strong>Skipped</strong><ul>${skipped}</ul></div>` : ""}
  `;
}

async function act(dryRun) {
  if (!dryRun) {
    const n = state.queue.length - excludedIds().length;
    if (!confirm(`Publish a new model version from ${n} contribution(s)? `
      + `This writes model_v(N+1).json and cannot be undone from here.`)) {
      return;
    }
  }
  try {
    const result = await runAggregation(state.adminKey,
      { exclude: excludedIds(), dryRun });
    renderResult(result);
    if (!dryRun && result.to_version) {
      await loadQueue();
    }
  } catch (error) {
    report("action-report", "error",
      `<strong>Request failed.</strong><p>${escapeHtml(error.message)}</p>`);
  }
}

/* ---------------------------------------------------------------------- */
/* 4 — historique                                                         */
/* ---------------------------------------------------------------------- */
async function loadHistory() {
  try {
    const { versions } = await fetchHistory();
    if (!versions?.length) {
      $("history").innerHTML = `<p class="muted">No version published yet.</p>`;
      show("step-history", true);
      return;
    }
    const rows = versions.map((v) => {
      const cells = Object.entries(v.targets).map(([name, t]) => {
        const scores = Object.entries(t.loo_r2)
          .map(([engine, r2]) => `${engine} ${r2 === null || r2 === undefined
            ? "—" : fmt(r2)}`)
          .join(" · ");
        return `<td><span class="tname">${escapeHtml(name)}</span> n=${t.n_train}
          <span class="muted">${scores}</span></td>`;
      }).join("");
      return `<tr><th>v${v.version}</th>
        <td>${formatDate(v.created_utc)}</td>${cells}</tr>`;
    }).join("");

    $("history").innerHTML = `<table class="history">
      <thead><tr><th>Version</th><th>Date</th>
        ${Object.keys(versions[0].targets).map((n) =>
          `<th>${escapeHtml(n)}</th>`).join("")}
      </tr></thead><tbody>${rows}</tbody></table>`;

    const latest = versions[versions.length - 1].version;
    $("rollback-select").innerHTML = versions
      .filter((v) => v.version !== latest)
      .map((v) => `<option value="${v.version}">v${v.version}` +
        ` — ${formatDate(v.created_utc)}</option>`)
      .reverse()
      .join("") || `<option value="">— no earlier version —</option>`;

    show("step-history", true);
  } catch {
    $("history").innerHTML = `<p class="muted">Version history unavailable.</p>`;
    $("rollback-select").innerHTML = "";
    show("step-history", true);
  }
}

/* ---------------------------------------------------------------------- */
/* 5 — retour à une version antérieure                                    */
/* ---------------------------------------------------------------------- */
async function doRollback() {
  const toVersion = Number($("rollback-select").value);
  if (!toVersion) return;
  if (!confirm(`Publish a new version with the exact content of v${toVersion}? `
    + `Nothing is deleted — the versions in between stay in the history.`)) {
    return;
  }
  try {
    const result = await rollbackTo(state.adminKey, toVersion);
    report("rollback-report", "ok", `<p><strong>${escapeHtml(result.message)}</strong></p>`);
    await loadHistory();
  } catch (error) {
    report("rollback-report", "error",
      `<strong>Rollback failed.</strong><p>${escapeHtml(error.message)}</p>`);
  }
}

/* ---------------------------------------------------------------------- */
wireThemeToggle();
wireAuth();
$("refresh-queue-button").addEventListener("click", loadQueue);
$("preview-button").addEventListener("click", () => act(true));
$("publish-button").addEventListener("click", () => act(false));
$("rollback-button").addEventListener("click", doRollback);
