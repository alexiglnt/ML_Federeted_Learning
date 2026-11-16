/* Reading a file and summarising it, entirely in the browser.
 *
 * This module is the privacy guarantee. Everything here runs on the
 * contributor's machine: the file is read with the FileReader API, the
 * measurements are turned into four sums, and only those sums are ever handed
 * to the network layer. No measurement passes through `lib/api.ts`.
 *
 * It is written without a dependency on purpose — the same reason the site
 * loads no web font. A researcher deciding whether to trust this page with
 * unpublished measurements can read it, and a supply chain they cannot read
 * would undermine the claim the page is making.
 *
 * Only delimited text is handled. `.xlsx` is a zip of XML and unpacking one
 * without a library is a project of its own, so the federated path accepts CSV
 * and tab-separated files and says so rather than failing obscurely. The shared
 * path still takes spreadsheets, because there the server does the reading.
 */

export interface LocalTable {
  columns: string[];
  /** Parsed rows, keyed by column heading. Numbers where a number was found. */
  rows: Record<string, number | string | null>[];
  separator: string;
  decimal: "." | ",";
  headerRow: number;
  skippedRows: number;
  notes: string[];
}

export interface SufficientStatistics {
  n: number;
  /** D'D with D = [1, X]. */
  dtd: number[][];
  dty: number[];
  yty: number;
}

const CANDIDATE_SEPARATORS = [",", ";", "\t"];

/** Split one line, respecting double quotes. */
function splitLine(line: string, separator: string): string[] {
  const cells: string[] = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"') {
      // A doubled quote inside a quoted field is a literal quote.
      if (quoted && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (char === separator && !quoted) {
      cells.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current);
  return cells.map((cell) => cell.trim().replace(/^"|"$/g, ""));
}

/** The separator that splits the most lines into the same number of cells.
 *
 *  Consistency rather than raw frequency: a European export uses semicolons
 *  between fields and commas inside numbers, and counting commas would win on
 *  frequency while being wrong. */
function detectSeparator(lines: string[]): string {
  let best = ",";
  let bestScore = -1;
  for (const separator of CANDIDATE_SEPARATORS) {
    const counts = lines.map((line) => splitLine(line, separator).length);
    const width = Math.max(...counts);
    if (width < 2) continue;
    const agreeing = counts.filter((count) => count === width).length;
    const score = agreeing * 100 + width;
    if (score > bestScore) {
      best = separator;
      bestScore = score;
    }
  }
  return best;
}

const PLAIN_NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
const COMMA_NUMBER = /^[-+]?(\d+,\d*|,\d+)([eE][-+]?\d+)?$/;

/** Whether the file writes decimals with a comma.
 *
 *  Load-bearing: a file read with the wrong decimal mark parses without
 *  complaint and every measurement silently becomes text or an integer. */
function detectDecimal(rows: string[][], separator: string): "." | "," {
  if (separator === ",") return ".";
  let commas = 0;
  let dots = 0;
  for (const row of rows) {
    for (const cell of row) {
      if (COMMA_NUMBER.test(cell)) commas++;
      else if (PLAIN_NUMBER.test(cell) && cell.includes(".")) dots++;
    }
  }
  return commas > dots ? "," : ".";
}

export function toNumber(
  raw: string | null | undefined,
  decimal: "." | "," = ".",
): number | null {
  if (raw === null || raw === undefined) return null;
  const text = String(raw).trim();
  if (text === "") return null;
  const normalised = decimal === "," ? text.replace(/\s/g, "").replace(",", ".") : text;
  if (!PLAIN_NUMBER.test(normalised)) return null;
  const value = Number(normalised);
  return Number.isFinite(value) ? value : null;
}

/** Parse delimited text into columns and rows.
 *
 *  Handles the cases the Python reader handles and that real files actually
 *  contain: a byte-order mark, title rows above the header, semicolons,
 *  decimal commas, and blank trailing lines. */
export function parseDelimited(text: string): LocalTable {
  const notes: string[] = [];
  const clean = text.replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  const lines = clean.split("\n").filter((line) => line.trim() !== "");
  if (lines.length < 2) {
    throw new Error("That file has no rows under its header.");
  }

  const separator = detectSeparator(lines.slice(0, 30));
  const cells = lines.map((line) => splitLine(line, separator));
  const width = Math.max(...cells.map((row) => row.length));

  // The header is the first full-width row that is not itself all numbers —
  // which is how a title line or a units line above the real header is skipped.
  let headerRow = 0;
  for (let i = 0; i < Math.min(cells.length, 20); i++) {
    const row = cells[i];
    if (!row || row.length < width) continue;
    const filled = row.filter((cell) => cell !== "");
    const numeric = filled.filter((cell) => PLAIN_NUMBER.test(cell) || COMMA_NUMBER.test(cell));
    if (filled.length >= 2 && numeric.length < filled.length) {
      headerRow = i;
      break;
    }
  }
  if (headerRow > 0) {
    notes.push(`${headerRow} row(s) above the header were skipped.`);
  }

  const header = cells[headerRow] ?? [];
  const columns = header.map((name, index) => name || `column ${index + 1}`);
  const body = cells.slice(headerRow + 1).filter((row) => row.length >= 2);
  const decimal = detectDecimal(body, separator);
  if (decimal === ",") {
    notes.push("Decimals are written with a comma in this file.");
  }

  let skipped = 0;
  const rows = body
    .map((row) => {
      if (row.every((cell) => cell === "")) {
        skipped++;
        return null;
      }
      const record: Record<string, number | string | null> = {};
      columns.forEach((column, index) => {
        const raw = row[index] ?? "";
        const value = toNumber(raw, decimal);
        record[column] = value !== null ? value : raw === "" ? null : raw;
      });
      return record;
    })
    .filter((row): row is Record<string, number | string | null> => row !== null);

  return { columns, rows, separator, decimal, headerRow, skippedRows: skipped, notes };
}

/**
 * Propose one column per wanted quantity, without reusing a column twice.
 *
 * Greedy over confidence, mirroring `suggest_mapping` on the server: two of a
 * project's inputs can both look plausible against the same heading, and
 * quietly mapping one column to both would fit a model on a duplicated column.
 * Assigning the strongest pairing first and taking that column out of play is
 * the cheap fix.
 */
export function suggestMapping(
  perColumn: {
    column: string;
    matches: { variable: { key: string }; confidence: number; exact: boolean }[];
  }[],
  wantedKeys: string[],
): Record<string, { column: string | null; confidence: number; exact: boolean }> {
  const wanted = new Set(wantedKeys);
  const scored: { key: string; column: string; confidence: number; exact: boolean }[] = [];
  for (const entry of perColumn) {
    for (const match of entry.matches) {
      if (wanted.has(match.variable.key)) {
        scored.push({
          key: match.variable.key,
          column: entry.column,
          confidence: match.confidence,
          exact: match.exact,
        });
      }
    }
  }
  scored.sort((a, b) => b.confidence - a.confidence);

  const assigned: Record<string, { column: string | null; confidence: number; exact: boolean }> = {};
  const takenColumns = new Set<string>();
  for (const item of scored) {
    if (assigned[item.key] || takenColumns.has(item.column)) continue;
    assigned[item.key] = {
      column: item.column,
      confidence: item.confidence,
      exact: item.exact,
    };
    takenColumns.add(item.column);
  }
  for (const key of wantedKeys) {
    if (!assigned[key]) assigned[key] = { column: null, confidence: 0, exact: false };
  }
  return assigned;
}

/** Rows usable for a fit: every mapped input and the target present as numbers. */
export function buildMatrix(
  table: LocalTable,
  featureColumns: string[],
  targetColumn: string,
): { X: number[][]; y: number[] } {
  const X: number[][] = [];
  const y: number[] = [];
  for (const row of table.rows) {
    const features = featureColumns.map((column) =>
      typeof row[column] === "number" ? (row[column] as number) : null,
    );
    const target = typeof row[targetColumn] === "number" ? (row[targetColumn] as number) : null;
    if (target === null || features.some((value) => value === null)) continue;
    X.push(features as number[]);
    y.push(target);
  }
  return { X, y };
}

/**
 * The four numbers that leave this machine: n, D'D, D'y and y'y with D = [1, X].
 *
 * They are additive across labs, which is what lets the server refit **exactly**
 * — not approximately, not a weighted average of models — as though it had the
 * pooled rows. See ARCHITECTURE.md §5.1.
 *
 * Note honestly what they are not: anonymous. On very few rows these sums
 * disclose a great deal, and on a single row they reproduce it exactly. That is
 * what the project's minimum row count is for, and the server enforces it.
 */
export function sufficientStatistics(X: number[][], y: number[]): SufficientStatistics {
  const n = X.length;
  const first = X[0];
  if (n === 0 || first === undefined) throw new Error("No usable rows.");
  const width = first.length + 1;

  const dtd: number[][] = Array.from({ length: width }, () =>
    new Array<number>(width).fill(0),
  );
  const dty = new Array<number>(width).fill(0);
  let yty = 0;

  for (let k = 0; k < n; k++) {
    const row = X[k];
    const target = y[k];
    if (row === undefined || target === undefined) continue;
    const design = [1, ...row];

    for (let i = 0; i < width; i++) {
      const di = design[i] ?? 0;
      const accumulator = dtd[i];
      if (accumulator === undefined) continue;
      dty[i] = (dty[i] ?? 0) + di * target;
      // Symmetric, so only the upper triangle is accumulated and mirrored.
      for (let j = i; j < width; j++) {
        accumulator[j] = (accumulator[j] ?? 0) + di * (design[j] ?? 0);
      }
    }
    yty += target * target;
  }

  for (let i = 0; i < width; i++) {
    const rowI = dtd[i];
    if (rowI === undefined) continue;
    for (let j = 0; j < i; j++) {
      rowI[j] = dtd[j]?.[i] ?? 0;
    }
  }

  return { n, dtd, dty, yty };
}

/** Min and max of each mapped input, over the rows behind the summary. */
export function featureRanges(
  table: LocalTable,
  mapping: Record<string, string>,
  featureKeys: string[],
): Record<string, [number, number]> {
  const out: Record<string, [number, number]> = {};
  for (const key of featureKeys) {
    const column = mapping[key];
    if (!column) continue;
    const values = table.rows
      .map((row) => (typeof row[column] === "number" ? (row[column] as number) : null))
      .filter((value): value is number => value !== null);
    if (values.length) out[key] = [Math.min(...values), Math.max(...values)];
  }
  return out;
}
