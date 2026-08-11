/* Enchaînement de l'interface : fichier -> colonnes -> scores -> contribution.
 *
 * Toute la logique de calcul est dans models.js et score.js ; ce fichier ne
 * fait que relier les écrans et présenter les résultats. Il garde l'état de la
 * session dans un seul objet, ce qui rend visible d'un coup d'œil ce que la
 * page connaît — et donc ce qu'elle pourrait envoyer.
 */

import {
  buildContribution, fetchHistory, fetchModel, fetchStatus, postContribution,
} from "./api.js";
import { sufficientStatistics } from "./models.js";
import {
  buildMatrix, featureRanges, guessFeatureMapping, guessTargetColumns,
  numericColumns, parseDelimited,
} from "./parse.js";
import { formatDate } from "./format.js";
import { interpret, refitScores, transferScores } from "./score.js";
import { wireThemeToggle } from "./theme.js";

const state = {
  model: null,
  status: null,
  table: null,      // { columns, rows, sep, decimal, headerRow }
  mapping: {},      // variable du modèle -> colonne du fichier
  target: null,
  result: null,     // { transfer, refit, stats, X, y }
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

/* ---------------------------------------------------------------------- */
/* Démarrage                                                              */
/* ---------------------------------------------------------------------- */
async function boot() {
  try {
    state.model = await fetchModel();
    const t = state.model.targets;
    const first = Object.values(t)[0];
    $("model-badge").textContent =
      `Global model v${state.model.version} — ${state.model.material}, `
      + `${state.model.features.join(", ")} — trained on ${first.n_train} `
      + `conditions from ${(first.n_contributions ?? 0) + 1} source(s)`;
  } catch (error) {
    $("model-badge").textContent =
      `The global model could not be loaded (${error.message}). `
      + `Scoring is unavailable until the server answers.`;
    $("model-badge").classList.add("error");
    return;
  }

  try {
    state.status = await fetchStatus();
    $("min-rows").textContent = String(state.status.min_rows ?? 5);
  } catch {
    // Sans /status la page reste utilisable pour le calcul local ; seule la
    // contribution risque d'échouer, et son propre message le dira.
  }

  renderHistory().catch(() => {
    $("history").innerHTML =
      `<p class="muted">Version history unavailable.</p>`;
  });
}

/* ---------------------------------------------------------------------- */
/* 1 — lecture du fichier                                                 */
/* ---------------------------------------------------------------------- */
function wireDropzone() {
  const zone = $("dropzone");
  const input = $("file-input");

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    if (input.files?.[0]) loadFile(input.files[0]);
  });

  ["dragenter", "dragover"].forEach((type) => {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.add("over");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.remove("over");
    });
  });
  zone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) loadFile(file);
  });
}

async function loadFile(file) {
  show("step-columns", false);
  show("step-results", false);
  show("step-contribute", false);

  if (/\.xlsx?$|\.xlsm$/i.test(file.name)) {
    report("file-report", "error",
      `<strong>Excel files are not supported yet.</strong> In Excel, use `
      + `<em>File &rsaquo; Save As</em> and choose <em>CSV</em>, then load the `
      + `CSV here. Semicolons and decimal commas are handled.`);
    return;
  }

  let text;
  try {
    text = await file.text();
  } catch (error) {
    report("file-report", "error", `The file could not be read: ${error.message}`);
    return;
  }

  try {
    state.table = parseDelimited(text);
  } catch (error) {
    report("file-report", "error", error.message);
    return;
  }

  const { columns, rows, sep, decimal, headerRow } = state.table;
  const numeric = numericColumns(columns, rows);
  const sepLabel = { ";": "semicolon", ",": "comma", "\t": "tab", "|": "pipe" }[sep] ?? sep;

  const notes = [
    `<strong>${file.name}</strong> — ${rows.length} row(s), ${columns.length} column(s)`,
    `Detected: ${sepLabel} separator, decimal ${decimal === "," ? "comma" : "point"}`
      + (headerRow > 0 ? `, header on line ${headerRow + 1}` : ""),
    `${numeric.length} numeric column(s): ${numeric.join(", ") || "none"}`,
  ];
  if (numeric.length < state.model.features.length + 1) {
    notes.push(`<span class="warn">Fewer numeric columns than the model needs `
      + `(${state.model.features.length} inputs + 1 target). Check the separator `
      + `and the decimal mark.</span>`);
  }
  report("file-report", "info", notes.map((n) => `<p>${n}</p>`).join(""));

  state.mapping = guessFeatureMapping(state.model.features, columns, rows);
  renderMapping();
  show("step-columns", true);
  $("step-columns").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------------------------------------------------------------- */
/* 2 — correspondance des colonnes                                        */
/* ---------------------------------------------------------------------- */
function renderMapping() {
  const { columns, rows } = state.table;
  const numeric = numericColumns(columns, rows);
  const units = state.model.feature_units ?? {};

  $("mapping").innerHTML = state.model.features.map((feature) => {
    const options = [`<option value="">— not found —</option>`]
      .concat(numeric.map((c) => `<option value="${escapeAttr(c)}"`
        + `${state.mapping[feature] === c ? " selected" : ""}>${escapeHtml(c)}</option>`))
      .join("");
    return `<div class="field-row">
      <label for="map-${feature}">${escapeHtml(feature)}
        ${units[feature] ? `<span class="unit">${escapeHtml(units[feature])}</span>` : ""}</label>
      <select id="map-${feature}" data-feature="${feature}">${options}</select>
    </div>`;
  }).join("");

  $("mapping").querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", () => {
      state.mapping[select.dataset.feature] = select.value;
      validateMapping();
    });
  });

  const targets = guessTargetColumns(columns, rows);
  const candidates = targets.length ? targets : numeric;
  const chosen = state.model.targets[state.target] ? state.target : null;
  $("target-select").innerHTML = candidates
    .map((c) => `<option value="${escapeAttr(c)}"`
      + `${chosen === c ? " selected" : ""}>${escapeHtml(c)}</option>`)
    .join("");
  state.target = $("target-select").value || null;
  $("target-select").addEventListener("change", () => {
    state.target = $("target-select").value;
    validateMapping();
  });

  validateMapping();
}

function validateMapping() {
  const issues = [];
  const missing = state.model.features.filter((f) => !state.mapping[f]);
  if (missing.length) {
    issues.push(`<span class="err">Unmatched input(s): <strong>`
      + `${missing.join(", ")}</strong>. The models need all `
      + `${state.model.features.length}.</span>`);
  }

  const used = Object.values(state.mapping).filter(Boolean);
  const duplicated = used.filter((c, i) => used.indexOf(c) !== i);
  if (duplicated.length) {
    issues.push(`<span class="err">Column <strong>${duplicated[0]}</strong> is `
      + `assigned to two different inputs.</span>`);
  }
  if (state.target && used.includes(state.target)) {
    issues.push(`<span class="err">Column <strong>${state.target}</strong> is `
      + `both the target and an input: the model would predict its own `
      + `value.</span>`);
  }

  let ready = issues.length === 0 && state.target;
  if (ready) {
    const columnsUsed = state.model.features.map((f) => state.mapping[f]);
    const { X, y, dropped } = buildMatrix(state.table.rows, columnsUsed, state.target);
    if (X.length < 3) {
      issues.push(`<span class="err">Only ${X.length} complete row(s). At least `
        + `3 are needed, and leave-one-out only means something from about `
        + `${state.model.features.length + 3} onwards.</span>`);
      ready = false;
    } else {
      if (dropped) {
        issues.push(`<span class="warn">${dropped} row(s) have a missing or `
          + `non-numeric value and will be ignored.</span>`);
      }
      if (X.length <= state.model.features.length + 1) {
        issues.push(`<span class="warn">${X.length} rows for `
          + `${state.model.features.length} inputs: the model has as much freedom `
          + `as it has data. It will fit perfectly and learn nothing. Read the `
          + `leave-one-out score, not the training score.</span>`);
      }
      state.model.features.forEach((f, j) => {
        const values = X.map((row) => row[j]);
        if (new Set(values).size === 1) {
          issues.push(`<span class="warn"><strong>${f}</strong> is constant `
            + `(${values[0]}): it carries no information, and the fit will be `
            + `numerically unstable.</span>`);
        }
      });
      issues.push(`<span class="ok">${X.length} usable row(s).</span>`);
    }
  }

  if (issues.length) {
    report("mapping-issues", "info", issues.map((i) => `<p>${i}</p>`).join(""));
  } else show("mapping-issues", false);
  $("run-button").disabled = !ready;
}

/* ---------------------------------------------------------------------- */
/* 3 — calcul des scores                                                  */
/* ---------------------------------------------------------------------- */
function runScores() {
  const columnsUsed = state.model.features.map((f) => state.mapping[f]);
  const { X, y } = buildMatrix(state.table.rows, columnsUsed, state.target);
  const targetKey = pickModelTarget();

  const transfer = transferScores(X, y, state.model.targets[targetKey]);
  const refit = refitScores(X, y, state.model);

  state.result = {
    X, y, transfer, refit, targetKey,
    stats: sufficientStatistics(X, y),
    ranges: featureRanges(X, state.model.features),
  };

  renderResults();
  show("step-results", true);
  show("step-contribute", true);
  refreshPayloadPreview();
  $("step-results").scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * À quelle grandeur du modèle global la colonne choisie correspond-elle ?
 *
 * Le modèle en connaît deux (longitudinale et transversale) et le nom de la
 * colonne du collègue ne les distingue pas forcément. On tente une
 * correspondance sur le nom, et à défaut on prend la première : le choix est
 * affiché à l'écran pour être vérifiable.
 */
function pickModelTarget() {
  const keys = Object.keys(state.model.targets);
  const norm = String(state.target).toLowerCase();
  const hit = keys.find((k) => norm.includes(k.toLowerCase()))
    ?? keys.find((k) => {
      const tail = k.split("_").pop().toLowerCase();
      return norm.includes(`_${tail}`) || norm.endsWith(tail);
    });
  return hit ?? keys[0];
}

function scoreRow(label, m) {
  const cls = m.R2 >= 0.5 ? "good" : (m.R2 < 0 ? "bad" : "mid");
  return `<div class="score-line">
    <span class="engine">${label}</span>
    <span class="r2 ${cls}">R² ${fmt(m.R2)}</span>
    <span class="rmse">RMSE ${fmt(m.RMSE, 1)} MPa</span>
  </div>`;
}

function renderResults() {
  const { transfer, refit, targetKey } = state.result;

  $("card-transfer").querySelector(".score-values").innerHTML =
    scoreRow("Linear", transfer.linear) + scoreRow("PIML", transfer.piml);
  $("card-refit").querySelector(".score-values").innerHTML =
    scoreRow("Linear", refit.engines.linear.loo)
    + scoreRow("PIML", refit.engines.piml.loo);

  const bestTransfer = Math.max(transfer.linear.R2, transfer.piml.R2);
  const bestRefit = Math.max(refit.engines.linear.loo.R2,
                             refit.engines.piml.loo.R2);
  $("reading").textContent = interpret(bestTransfer, bestRefit);

  const published = state.model.targets[targetKey].engines;
  const coefTable = (engine, theta, space) => `
    <table class="coef">
      <caption>${engine} — fitted on your data (${space === "raw"
        ? "physical units" : "standardised inputs"})</caption>
      <tbody>
        <tr><th>intercept</th><td>${fmt(theta[0], 2)}</td></tr>
        ${state.model.features.map((f, j) =>
          `<tr><th>${escapeHtml(f)}</th><td>${fmt(theta[j + 1], 4)}</td></tr>`).join("")}
      </tbody>
    </table>`;

  $("details-body").innerHTML = `
    <p class="muted">
      Compared against <strong>${escapeHtml(targetKey)}</strong> of global model
      v${state.model.version}, whose published leave-one-out scores are
      linear R² ${fmt(published.linear.loo?.R2)} and
      PIML R² ${fmt(published.piml.loo?.R2)}
      on ${state.model.targets[targetKey].n_train} conditions.
    </p>
    <div class="two-col">
      ${coefTable("Linear", [refit.engines.linear.intercept,
                             ...refit.engines.linear.coef], "standardised")}
      ${coefTable(`PIML (λ = ${refit.engines.piml.lambda})`,
                  [refit.engines.piml.intercept,
                   ...refit.engines.piml.coef], "raw")}
    </div>
    <p class="muted">
      Training scores, shown for completeness only — on this many rows they are
      not informative: linear R² ${fmt(refit.engines.linear.train.R2)},
      PIML R² ${fmt(refit.engines.piml.train.R2)}.
    </p>
    ${(refit.engines.linear.ridge || refit.engines.piml.ridge)
      ? `<p class="warn">The fit needed a small numerical stabilisation: two of
         your inputs are nearly proportional, so the individual coefficients
         should not be read as physical effects.</p>` : ""}`;
}

/* ---------------------------------------------------------------------- */
/* 4 — contribution                                                       */
/* ---------------------------------------------------------------------- */
function collectForm() {
  const value = (id) => $(id).value.trim();
  return {
    contributor: {
      name: value("c-name"),
      lab: value("c-lab"),
      email: value("c-email") || null,
    },
    dataset: {
      n_rows: state.result?.stats.n ?? 0,
      material: value("c-material"),
      process: value("c-process") || null,
      coolant: value("c-coolant") || null,
      measurement_method: $("c-method").value,
      feature_ranges: state.result?.ranges ?? {},
      notes: value("c-notes") || null,
    },
    key: value("c-key"),
  };
}

function currentPayload() {
  const form = collectForm();
  const { refit, transfer, stats, targetKey } = state.result;
  return buildContribution({
    model: state.model,
    target: targetKey,
    features: state.model.features,
    contributor: form.contributor,
    dataset: form.dataset,
    stats,
    localFit: {
      linear: {
        space: "standardised",
        intercept: refit.engines.linear.intercept,
        coef: refit.engines.linear.coef,
        train: refit.engines.linear.train,
        loo: refit.engines.linear.loo,
      },
      piml: {
        space: "raw",
        lambda: refit.engines.piml.lambda,
        intercept: refit.engines.piml.intercept,
        coef: refit.engines.piml.coef,
        train: refit.engines.piml.train,
        loo: refit.engines.piml.loo,
      },
    },
    scores: {
      transfer_linear: transfer.linear,
      transfer_piml: transfer.piml,
      refit_linear_loo: refit.engines.linear.loo,
      refit_piml_loo: refit.engines.piml.loo,
    },
  });
}

/**
 * L'aperçu est recalculé à chaque frappe, à dessein : la promesse « rien
 * d'autre ne part » n'a de valeur que si elle est vérifiable à tout moment,
 * sur le contenu réel de l'envoi.
 */
function refreshPayloadPreview() {
  if (!state.result) return;
  $("payload-preview").textContent = JSON.stringify(currentPayload(), null, 2);
}

async function submitContribution(event) {
  event.preventDefault();
  const form = collectForm();

  const missing = [
    !form.contributor.name && "your name",
    !form.contributor.lab && "your laboratory",
    !form.dataset.material && "the material",
    !form.key && "the access key",
  ].filter(Boolean);
  if (missing.length) {
    report("contribute-report", "error",
      `Please fill in: ${missing.join(", ")}.`);
    return;
  }

  const minRows = state.status?.min_rows ?? 5;
  if (form.dataset.n_rows < minRows) {
    report("contribute-report", "error",
      `Contributions need at least ${minRows} rows; yours has `
      + `${form.dataset.n_rows}. This is a privacy threshold, not a statistical `
      + `one — see the note above. You can still use the scores locally.`);
    return;
  }

  const button = $("send-button");
  button.disabled = true;
  button.textContent = "Sending…";
  try {
    const answer = await postContribution(currentPayload(), form.key);
    report("contribute-report", "ok",
      `<strong>Thank you — contribution ${answer.id} received.</strong>`
      + `<p>${escapeHtml(answer.message)}</p>`);
    button.textContent = "Sent";
  } catch (error) {
    report("contribute-report", "error",
      `<strong>The contribution could not be sent.</strong>`
      + `<pre>${escapeHtml(error.message)}</pre>`
      + `<p>You can use “Download it instead” and email us the file.</p>`);
    button.disabled = false;
    button.textContent = "Send my contribution";
  }
}

/**
 * Repli utile : si le serveur est inaccessible, ou si le collègue préfère faire
 * relire l'envoi par son service juridique avant qu'il ne parte, le même
 * contenu exact est téléchargeable et peut arriver par courriel.
 */
function downloadContribution() {
  const payload = currentPayload();
  const blob = new Blob([JSON.stringify(payload, null, 2)],
                        { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const lab = (payload.contributor.lab || "contribution")
    .replace(/[^\w-]+/g, "_").slice(0, 40);
  link.href = url;
  link.download = `deam_contribution_${lab}_${payload.target}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

/* ---------------------------------------------------------------------- */
/* 5 — historique                                                         */
/* ---------------------------------------------------------------------- */
async function renderHistory() {
  const { versions } = await fetchHistory();
  if (!versions?.length) {
    $("history").innerHTML = `<p class="muted">No version published yet.</p>`;
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
        `<th>${escapeHtml(n)} — leave-one-out R²</th>`).join("")}
    </tr></thead><tbody>${rows}</tbody></table>
    <p class="muted">
      From version 2 onwards the leave-one-out R² is shown as “—”: cross
      validation needs individual points, and the pooled model is refitted from
      sums only. The contributing labs' own scores are recorded inside the model
      file instead.
    </p>`;
}

/* ---------------------------------------------------------------------- */
/* Utilitaires                                                            */
/* ---------------------------------------------------------------------- */
function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const escapeAttr = escapeHtml;

/* ---------------------------------------------------------------------- */
wireThemeToggle();
wireDropzone();
$("run-button").addEventListener("click", runScores);
$("contribute-form").addEventListener("submit", submitContribution);
$("contribute-form").addEventListener("input", refreshPayloadPreview);
$("download-button").addEventListener("click", downloadContribution);
boot();
