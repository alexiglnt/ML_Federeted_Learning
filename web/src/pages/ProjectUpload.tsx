/* Adding measurements to a project, in either of the two modes.
 *
 * Three visible stages: choose a file, check how it was read and confirm the
 * column mapping, then submit. The middle stage is the one that earns its place
 * — a file read with the wrong decimal mark or the wrong header row parses
 * without complaint, and the mistake is obvious in a preview table and
 * invisible in a summary line.
 *
 * The two modes differ in **where the file is read**, and that difference is
 * the entire privacy guarantee:
 *
 *   shared     the file is uploaded; the server parses it and keeps it. The
 *              owner can read it. This is what unlocks model access.
 *   federated  the file is read by `lib/federated.ts` in this browser and never
 *              leaves the machine. Only four sums per target are transmitted.
 *              Credited and counted — but no model access, because no data was
 *              shared. See ARCHITECTURE.md §4.
 *
 * The page also serves the conversion path (`?share=<id>`): a contributor who
 * sent sums and now wants the model uploads their file against the *existing*
 * contribution rather than making a new one. ARCHITECTURE.md §5.5 explains why
 * that has to be the same row.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  projects as projectsApi,
  uploads as uploadsApi,
  variables as variablesApi,
  type ContributionOut,
  type ProjectDetail,
  type UploadPreview,
} from "../lib/api";
import {
  buildMatrix,
  featureRanges,
  parseDelimited,
  suggestMapping,
  sufficientStatistics,
  type LocalTable,
} from "../lib/federated";

const METHODS = ["XRD", "hole-drilling", "neutron", "contour", "other"] as const;

type Mode = "shared" | "federated";
type Suggestion = { column: string | null; confidence: number; exact: boolean };

function Confidence({ value, exact }: { value: number; exact: boolean }) {
  if (exact) return <span className="badge">exact</span>;
  if (value <= 0) return <span className="muted small">no suggestion</span>;
  return <span className="badge warn">approximate · {Math.round(value * 100)}%</span>;
}

export default function ProjectUpload() {
  const { slug } = useParams<{ slug: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();

  // Set when converting an existing federated contribution to shared.
  const shareId = params.get("share") ? Number(params.get("share")) : null;

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [mode, setMode] = useState<Mode>("shared");

  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [local, setLocal] = useState<LocalTable | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, Suggestion>>({});

  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [method, setMethod] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<ContributionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!slug) return;
    projectsApi.get(slug).then(setProject).catch(() => setProject(null));
  }, [slug]);

  function reset() {
    setPreview(null);
    setLocal(null);
    setSuggestions({});
    setMapping({});
  }

  function adoptSuggestions(found: Record<string, Suggestion>) {
    setSuggestions(found);
    const initial: Record<string, string> = {};
    for (const [key, suggestion] of Object.entries(found)) {
      if (suggestion.column) initial[key] = suggestion.column;
    }
    setMapping(initial);
  }

  async function choose(file: File) {
    if (!slug || !project) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (mode === "shared") {
        const data = await uploadsApi.preview(slug, file);
        setLocal(null);
        setPreview(data);
        adoptSuggestions(data.suggested_mapping);
      } else {
        // Read here, in this tab. Nothing is sent.
        const table = parseDelimited(await file.text());
        setPreview(null);
        setLocal(table);
        // Only the column *headings* go to the server, to be matched against
        // the registry. A heading is not a measurement, and reimplementing the
        // matcher here would guarantee it drifted from the server's.
        const perColumn = await variablesApi.match(table.columns);
        const wanted = [
          ...project.inputs.map((item) => item.variable.key),
          ...project.targets.map((item) => item.variable.key),
        ];
        adoptSuggestions(suggestMapping(perColumn, wanted));
      }
    } catch (caught) {
      reset();
      setError(caught instanceof Error ? caught.message : "Could not read that file.");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!slug || !project) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "federated") {
        if (!local) return;
        const featureKeys = project.inputs.map((item) => item.variable.key);
        // Every input, not merely the required ones: the design matrix has one
        // column per declared input and the server checks its width. A summary
        // missing a column describes a different project.
        const featureColumns = featureKeys.map((key) => mapping[key] ?? "");
        const stats: Record<string, ReturnType<typeof sufficientStatistics>> = {};
        for (const target of project.targets) {
          const column = mapping[target.variable.key];
          if (!column) continue;
          const { X, y } = buildMatrix(local, featureColumns, column);
          if (X.length === 0) {
            throw new Error(
              `No row has every input and ${target.variable.display_name} as a number.`,
            );
          }
          stats[target.variable.key] = sufficientStatistics(X, y);
        }
        const contribution = await uploadsApi.federated(slug, {
          stats,
          feature_ranges: featureRanges(local, mapping, featureKeys),
          column_mapping: mapping,
          measurement_method: method || undefined,
          notes: notes || undefined,
        });
        setResult(contribution);
        reset();
        return;
      }

      if (!preview) return;
      if (shareId !== null) {
        const converted = await uploadsApi.share(slug, shareId, {
          upload_token: preview.upload_token,
          mapping,
          measurement_method: method || undefined,
          notes: notes || undefined,
        });
        setResult(converted.contribution);
      } else {
        setResult(
          await uploadsApi.commit(slug, {
            upload_token: preview.upload_token,
            mapping,
            mode: "shared",
            measurement_method: method || undefined,
            notes: notes || undefined,
          }),
        );
      }
      reset();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not submit.");
    } finally {
      setBusy(false);
    }
  }

  if (!project) return <p className="muted">Loading…</p>;

  const isOwner = project.viewer_role === "owner";
  const federatedAllowed = project.accepts_federated && shareId === null;
  const wanted = [
    ...project.inputs.map((item) => ({ ...item.variable, role: "input" as const })),
    ...project.targets.map((item) => ({ ...item.variable, role: "target" as const })),
  ];
  const columns = mode === "shared" ? (preview?.columns ?? []) : (local?.columns ?? []);
  const previewRows =
    mode === "shared" ? (preview?.preview_rows ?? []) : (local?.rows.slice(0, 8) ?? []);
  const ready = mode === "shared" ? preview !== null : local !== null;

  // Sharing a file can leave an optional input unmapped — the server drops those
  // rows or the column. A summary cannot: the design matrix behind it must have
  // exactly one column per declared input, so federated mode needs all of them.
  const unmappedRequired = project.inputs.filter(
    (item) =>
      (mode === "federated" || item.required) && !mapping[item.variable.key],
  );
  const anyTarget = project.targets.some((item) => mapping[item.variable.key]);
  const canSubmit = unmappedRequired.length === 0 && anyTarget && !busy;

  return (
    <section>
      <p className="eyebrow">
        <Link to={`/projects/${project.slug}`}>{project.title}</Link>
      </p>
      <h1>
        {shareId !== null
          ? "Share your file"
          : isOwner
            ? "Add measurements"
            : "Contribute your measurements"}
      </h1>

      {shareId !== null && (
        <div className="notice">
          <p>
            You already contributed summary statistics to this project. Uploading
            your file now <strong>replaces those statistics with the rows
            themselves</strong> — it stays the same contribution, so your data is
            never counted twice — and it unlocks the model for you.
          </p>
        </div>
      )}

      {/* 1 --------------------------------------------------------------- */}
      <h2>
        <span className="num">1</span> How you want to contribute
      </h2>
      {federatedAllowed ? (
        <div className="mode-grid">
          <label className={`mode-card${mode === "shared" ? " chosen" : ""}`}>
            <input
              type="radio"
              name="mode"
              className="tiny"
              checked={mode === "shared"}
              onChange={() => {
                setMode("shared");
                reset();
              }}
            />
            <strong> Share my file</strong>
            <ul>
              <li>The project owner can read your measurements.</li>
              <li>Feeds both the main model and the reference model.</li>
              <li>
                <strong>Unlocks the model</strong> once the owner accepts it.
              </li>
              <li>Every download of your file is logged and shown to you.</li>
            </ul>
          </label>
          <label className={`mode-card${mode === "federated" ? " chosen" : ""}`}>
            <input
              type="radio"
              name="mode"
              className="tiny"
              checked={mode === "federated"}
              onChange={() => {
                setMode("federated");
                reset();
              }}
            />
            <strong> Keep my data, send only summaries</strong>
            <ul>
              <li>
                Your file is read in this browser. Only four sums per quantity
                are transmitted — no measurement leaves your machine.
              </li>
              <li>
                Feeds the linear reference model, <em>exactly</em> as if the rows
                had been pooled. Not an approximation.
              </li>
              <li>You are credited, and your data widens the published range.</li>
              <li>
                <strong>Does not unlock the model.</strong> You can share your
                file later to change that.
              </li>
            </ul>
          </label>
        </div>
      ) : (
        !project.accepts_federated && (
          <p className="muted">
            This project only accepts contributions that include the data.
          </p>
        )
      )}

      {/* 2 --------------------------------------------------------------- */}
      <h2>
        <span className="num">2</span> Your file
      </h2>
      {mode === "shared" ? (
        <p className="muted">
          CSV, tab-separated text, or .xlsx. Semicolon separators, decimal commas
          and title rows above the header are handled automatically, as are Greek
          letters and units in column names.
        </p>
      ) : (
        <p className="muted">
          CSV or tab-separated text. Spreadsheets are not supported in this mode:
          reading one would need a library, and this page deliberately loads no
          third-party code — it is what lets you check that nothing leaves.
          Export your sheet as CSV, or share the file instead.
        </p>
      )}
      <input
        type="file"
        accept={mode === "shared" ? ".csv,.txt,.tsv,.xlsx,.xlsm" : ".csv,.txt,.tsv"}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void choose(file);
        }}
      />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {ready && (
        <>
          <h2>
            <span className="num">3</span> How it was read
          </h2>
          <p className="meta-line small">
            {mode === "shared" && preview ? (
              <>
                <span>{preview.filename}</span>
                <span>{preview.parse_report.n_rows} rows</span>
                <span>{preview.parse_report.n_columns} columns</span>
                {preview.parse_report.separator && (
                  <span>separator “{preview.parse_report.separator}”</span>
                )}
                <span>decimal “{preview.parse_report.decimal}”</span>
              </>
            ) : (
              local && (
                <>
                  <span>{local.rows.length} rows</span>
                  <span>{local.columns.length} columns</span>
                  <span>
                    separator “{local.separator === "\t" ? "tab" : local.separator}”
                  </span>
                  <span>decimal “{local.decimal}”</span>
                  <span className="badge">read in your browser</span>
                </>
              )
            )}
          </p>
          {(mode === "shared" ? preview?.parse_report.notes ?? [] : local?.notes ?? []).map(
            (note) => (
              <p key={note} className="muted small">
                {note}
              </p>
            ),
          )}

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column} scope="col">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, index) => (
                  <tr key={index}>
                    {columns.map((column) => (
                      <td key={column}>{row[column] ?? "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Check the numbers look like numbers. If a column of measurements
            reads as text, the decimal mark was misread.
          </p>

          <h2>
            <span className="num">4</span> Match your columns
          </h2>
          <p className="muted">
            Confirm each one. An approximate match is a suggestion, not a
            verdict — a column matched to the wrong quantity fits the model to
            the wrong thing, and nothing would look broken afterwards.
          </p>

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Project quantity</th>
                  <th scope="col">Your column</th>
                  <th scope="col">Match</th>
                </tr>
              </thead>
              <tbody>
                {wanted.map((variable) => {
                  const suggestion = suggestions[variable.key];
                  const chosen = mapping[variable.key] ?? "";
                  const isSuggested = suggestion?.column === chosen && chosen !== "";
                  return (
                    <tr key={variable.key}>
                      <td>
                        <strong>{variable.display_name}</strong>
                        {variable.unit && <span className="muted"> · {variable.unit}</span>}
                        <br />
                        <span className="small muted">
                          {variable.role === "input" ? "input" : "target"}
                        </span>
                      </td>
                      <td>
                        <select
                          aria-label={`Column for ${variable.display_name}`}
                          value={chosen}
                          onChange={(e) =>
                            setMapping((current) => {
                              const next = { ...current };
                              if (e.target.value) next[variable.key] = e.target.value;
                              else delete next[variable.key];
                              return next;
                            })
                          }
                        >
                          <option value="">— not in my file —</option>
                          {columns.map((column) => (
                            <option key={column} value={column}>
                              {column}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {chosen === "" ? (
                          <span className="muted small">skipped</span>
                        ) : isSuggested && suggestion ? (
                          <Confidence value={suggestion.confidence} exact={suggestion.exact} />
                        ) : (
                          <span className="badge">chosen by you</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {unmappedRequired.length > 0 && (
            <p className="muted">
              Still unmatched:{" "}
              {unmappedRequired.map((item) => item.variable.display_name).join(", ")}.
              {mode === "federated" &&
                " Sending summaries needs every input matched, because the summary" +
                  " describes one column per input and the server checks that it fits."}
            </p>
          )}
          {!anyTarget && (
            <p className="muted">
              At least one target quantity must be matched — otherwise there is
              nothing to predict.
            </p>
          )}

          <h2>
            <span className="num">5</span> About these measurements
          </h2>
          <div className="field-row">
            <label htmlFor="method">
              Measurement method{" "}
              <span className="hint">
                methods disagree — XRD and hole drilling differ by tens of MPa on
                the same part
              </span>
            </label>
            <select id="method" value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="">— not specified —</option>
              {METHODS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="field-row wide">
            <label htmlFor="notes">
              Notes <span className="hint">anything needed to read your data correctly</span>
            </label>
            <textarea
              id="notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {mode === "federated" && (
            <div className="notice">
              <p>
                <strong>What will be sent.</strong> For each target quantity:
                the number of rows, the sums of the inputs and their products,
                and the same against the target. That is four numbers per
                quantity and nothing else — no row, no column of measurements,
                not the file.
              </p>
              <p className="muted small">
                Being honest about the limit: these sums are not anonymous. On
                very few rows they disclose a great deal, which is why a minimum
                row count is enforced.
              </p>
            </div>
          )}

          <div className="cta-row">
            <button className="primary" type="button" disabled={!canSubmit} onClick={submit}>
              {busy
                ? "Submitting…"
                : mode === "federated"
                  ? "Send summary statistics"
                  : shareId !== null
                    ? "Share my file"
                    : isOwner
                      ? "Add to my project"
                      : "Submit contribution"}
            </button>
            <button type="button" className="ghost" onClick={reset}>
              Cancel
            </button>
          </div>
        </>
      )}

      {/* Result ---------------------------------------------------------- */}
      {result && (
        <>
          <h2>Submitted</h2>
          <div className="notice">
            <p>
              <strong>{result.n_rows} rows</strong>{" "}
              {result.mode === "federated"
                ? "were summarised and the summary was sent. Your file stayed on your machine."
                : `accepted from ${result.original_filename}.`}{" "}
              {result.status === "pending"
                ? "It is now waiting for the project owner to review it."
                : "It is part of your project."}
            </p>
            {result.mode === "federated" && (
              <p className="muted small">
                This contribution improves the project's reference model and
                widens its published range, and you are credited for it. It does
                not unlock the model — you can share the file later from the
                project page to do that.
              </p>
            )}
          </div>

          {result.validation && result.validation.warnings.length > 0 && (
            <>
              <h3>Worth knowing</h3>
              <ul className="warning-list">
                {result.validation.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </>
          )}

          <div className="cta-row">
            <button
              type="button"
              className="primary"
              onClick={() => navigate(`/projects/${project.slug}`)}
            >
              Back to the project
            </button>
          </div>
        </>
      )}
    </section>
  );
}
