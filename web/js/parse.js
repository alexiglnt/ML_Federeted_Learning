/* Lecture du fichier de mesures, dans le navigateur.
 *
 * Les collègues arrivent avec des fichiers hétéroclites : point-virgule des
 * exports Excel européens, virgule décimale, lignes de titre avant l'en-tête,
 * lettres grecques dans les noms de colonnes. Ce module absorbe cette
 * diversité — c'est la transposition en JavaScript de la logique éprouvée dans
 * DeamApp/deamapp/engine/dataio.py, dont l'expérience a montré qu'elle est
 * nécessaire sur des fichiers réels.
 *
 * Limite assumée de cette version : le CSV et le texte tabulé uniquement. Lire
 * un .xlsx dans le navigateur demande de décompresser un ZIP et d'analyser du
 * XML ; c'est faisable mais hors sujet pour un premier jet, et le gabarit
 * fourni est en CSV. Un fichier Excel est refusé avec un message qui explique
 * comment l'enregistrer en CSV.
 */

const MAX_HEADER_SCAN = 8;

/** Découpe une ligne en respectant les guillemets. */
function splitLine(line, sep) {
  const cells = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"';
        i++;
      } else quoted = !quoted;
    } else if (ch === sep && !quoted) {
      cells.push(current);
      current = "";
    } else current += ch;
  }
  cells.push(current);
  return cells.map((c) => c.trim());
}

/** Un texte est-il lisible comme nombre, virgule décimale comprise ? */
function toNumber(text, decimal) {
  if (text === null || text === undefined) return NaN;
  let s = String(text).trim();
  if (!s) return NaN;
  if (decimal === ",") s = s.replace(/\./g, "").replace(",", ".");
  // Les espaces insécables des séparateurs de milliers d'Excel.
  s = s.replace(/[\s  ]/g, "");
  const value = Number(s);
  return Number.isFinite(value) ? value : NaN;
}

function looksNumeric(name) {
  const s = String(name ?? "").trim().replace(",", ".");
  return s !== "" && Number.isFinite(Number(s));
}

function isPlaceholder(name) {
  const s = String(name ?? "").trim();
  return s === "" || s.toLowerCase() === "nan";
}

/**
 * Note une tentative de lecture : combien de colonnes sont réellement
 * numériques.
 *
 * On ne peut pas se contenter de la première tentative qui « tient » : un
 * export Excel français se laisse lire avec le point comme décimale sans lever
 * d'erreur, mais toutes les colonnes de mesures arrivent en texte et
 * disparaissent ensuite des variables proposées. D'où la notation.
 */
function scoreAttempt(rows, headerRow, decimal) {
  if (rows.length <= headerRow + 1) return -Infinity;
  const header = rows[headerRow];
  const body = rows.slice(headerRow + 1);
  if (header.length < 2) return -Infinity;

  let numericCols = 0;
  for (let j = 0; j < header.length; j++) {
    let ok = 0;
    let seen = 0;
    for (const row of body) {
      if (j >= row.length) continue;
      seen++;
      if (Number.isFinite(toNumber(row[j], decimal))) ok++;
    }
    if (seen > 0 && ok / seen > 0.7) numericCols++;
  }
  const named = header.filter((c) => !isPlaceholder(c) && !looksNumeric(c)).length;
  const numericNames = header.filter(looksNumeric).length;
  const placeholders = header.filter(isPlaceholder).length;

  // Un nom de colonne qui se lit comme un nombre est lourdement pénalisé :
  // c'est le symptôme d'une ligne de données prise pour l'en-tête.
  return numericCols * 100 + named * 2 + header.length
    - placeholders * 6 - numericNames * 20;
}

/**
 * Analyse un texte CSV : détecte séparateur, décimale et ligne d'en-tête.
 * Renvoie { columns, rows, sep, decimal, headerRow, skipped }.
 */
export function parseDelimited(text, options = {}) {
  const clean = text.replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  const lines = clean.split("\n").filter((l) => l.trim() !== "");
  if (lines.length < 2) {
    throw new Error("The file does not contain enough lines to form a "
      + "table (one header line and at least one line of measurements).");
  }

  let best = null;
  const seps = options.sep ? [options.sep] : [";", ",", "\t", "|"];
  const decimals = options.decimal ? [options.decimal] : [".", ","];
  const headerRows = options.headerRow !== undefined
    ? [options.headerRow]
    : Array.from({ length: Math.min(MAX_HEADER_SCAN, lines.length - 1) },
                 (_, i) => i);

  for (const sep of seps) {
    const rows = lines.map((l) => splitLine(l, sep));
    for (const decimal of decimals) {
      // Une virgule ne peut pas être à la fois séparateur de colonnes et
      // séparateur décimal.
      if (sep === "," && decimal === ",") continue;
      for (const headerRow of headerRows) {
        const score = scoreAttempt(rows, headerRow, decimal);
        if (!best || score > best.score) {
          best = { score, sep, decimal, headerRow, rows };
        }
      }
    }
  }
  if (!best || best.score === -Infinity) {
    throw new Error("This file cannot be read as a table. "
      + "Check that it contains a line of column names and that the "
      + "columns are separated by commas, semicolons or tabs.");
  }

  const header = best.rows[best.headerRow];
  const columns = header.map((name, j) => (isPlaceholder(name)
    ? `column ${j + 1}`
    : String(name)));
  const body = best.rows.slice(best.headerRow + 1)
    .filter((row) => row.some((cell) => cell !== ""));

  const rows = body.map((row) => {
    const record = {};
    columns.forEach((name, j) => {
      const raw = j < row.length ? row[j] : "";
      const value = toNumber(raw, best.decimal);
      record[name] = Number.isFinite(value) ? value : (raw === "" ? null : raw);
    });
    return record;
  });

  return {
    columns,
    rows,
    sep: best.sep,
    decimal: best.decimal,
    headerRow: best.headerRow,
    skipped: best.headerRow,
  };
}

/** Colonnes dont au moins 70 % des valeurs sont numériques. */
export function numericColumns(columns, rows) {
  return columns.filter((c) => {
    const values = rows.map((r) => r[c]);
    const ok = values.filter((v) => typeof v === "number" && Number.isFinite(v));
    return values.length > 0 && ok.length / values.length > 0.7;
  });
}

/* ---------------------------------------------------------------------- */
/* Reconnaissance des colonnes                                            */
/* ---------------------------------------------------------------------- */

// Sans cette table, « γ (°) » et « rβ (µm) » disparaissent au filtrage et les
// colonnes deviennent méconnaissables — c'est exactement ce qui arrive au
// fichier de l'étude.
const GREEK = {
  "γ": "gamma", "β": "beta", "α": "alpha", "θ": "theta", "σ": "sigma",
  "τ": "tau", "λ": "lambda", "μ": "mu", "µ": "mu", "ρ": "rho", "φ": "phi",
  "ω": "omega", "Δ": "delta", "δ": "delta",
};

/** Forme canonique d'un nom : sans accents, sans unités, sans ponctuation. */
export function normalise(name) {
  let s = String(name ?? "");
  for (const [greek, latin] of Object.entries(GREEK)) s = s.split(greek).join(latin);
  s = s.replace(/\([^)]*\)|\[[^\]]*\]/g, " ");
  s = s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  s = s.replace(/[^a-z0-9]+/g, " ");
  return s.trim().split(/\s+/).join(" ");
}

const FEATURE_HINTS = {
  gamma: ["gamma", "rake", "angle de coupe", "angle coupe", "rake angle"],
  r_beta: ["r beta", "rbeta", "edge radius", "rayon arete", "acuite", "arete"],
  Vc: ["vc", "vitesse de coupe", "vitesse coupe", "cutting speed", "speed"],
  h: ["h", "epaisseur", "chip thickness", "thickness", "avance", "feed",
      "feed rate", "uncut chip thickness"],
};

const TARGET_HINTS = ["srs", "residual stress", "contrainte", "sigma", "stress",
                      "rs axial", "rs circumferential"];

/**
 * Associe chaque variable attendue par le modèle global à une colonne du
 * fichier. Purement indicatif : l'utilisateur corrige à l'écran. Le but est que
 * le cas courant — un fichier issu du gabarit — soit déjà juste.
 */
export function guessFeatureMapping(modelFeatures, columns, rows) {
  const numeric = numericColumns(columns, rows);
  const mapping = {};
  const taken = new Set();

  for (const feature of modelFeatures) {
    const hints = FEATURE_HINTS[feature] ?? [feature.toLowerCase()];
    let found = null;
    // Correspondance exacte d'abord, sinon inclusion : « Vc » ne doit pas être
    // capté par « Vc_max » si une colonne « Vc » existe.
    for (const pass of ["exact", "loose"]) {
      for (const column of numeric) {
        if (taken.has(column)) continue;
        const norm = normalise(column);
        const hit = pass === "exact"
          ? hints.some((h) => norm === h)
          : hints.some((h) => norm.split(" ").includes(h) || norm.includes(h));
        if (hit) {
          found = column;
          break;
        }
      }
      if (found) break;
    }
    if (found) {
      mapping[feature] = found;
      taken.add(found);
    } else mapping[feature] = "";
  }
  return mapping;
}

/** Colonnes qui ressemblent à une contrainte résiduelle mesurée. */
export function guessTargetColumns(columns, rows) {
  const numeric = numericColumns(columns, rows);
  return numeric.filter((c) => {
    const norm = normalise(c);
    return TARGET_HINTS.some((h) => norm.includes(h));
  });
}

/**
 * Construit X et y à partir de la correspondance choisie, en ne gardant que les
 * lignes complètes. Les lignes écartées sont comptées pour être signalées.
 */
export function buildMatrix(rows, featureColumns, targetColumn) {
  const X = [];
  const y = [];
  let dropped = 0;
  for (const row of rows) {
    const values = featureColumns.map((c) => row[c]);
    const target = row[targetColumn];
    const ok = values.every((v) => typeof v === "number" && Number.isFinite(v))
      && typeof target === "number" && Number.isFinite(target);
    if (!ok) {
      dropped++;
      continue;
    }
    X.push(values);
    y.push(target);
  }
  return { X, y, dropped };
}

/** Étendue de chaque variable — la seule chose transmise sur les entrées. */
export function featureRanges(X, featureNames) {
  const ranges = {};
  featureNames.forEach((name, j) => {
    const values = X.map((row) => row[j]);
    ranges[name] = [Math.min(...values), Math.max(...values)];
  });
  return ranges;
}
