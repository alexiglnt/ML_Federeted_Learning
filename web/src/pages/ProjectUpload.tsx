/* Adding measurements to a project.
 *
 * Three visible stages on one page: choose a file, check how it was read and
 * confirm the column mapping, then submit. The middle stage is the one that
 * earns its place — a file read with the wrong decimal mark or the wrong
 * header row parses without complaint, and the mistake is obvious in a preview
 * table and invisible in a summary line.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  projects as projectsApi,
  uploads as uploadsApi,
  type ContributionOut,
  type ProjectDetail,
  type UploadPreview,
} from "../lib/api";
import { useEffect } from "react";

const METHODS = [
  "XRD",
  "hole-drilling",
  "neutron",
  "contour",
  "other",
] as const;

function Confidence({ value, exact }: { value: number; exact: boolean }) {
  if (exact) return <span className="badge">exact</span>;
  if (value <= 0) return <span className="muted small">no suggestion</span>;
  return (
    <span className="badge warn">approximate · {Math.round(value * 100)}%</span>
  );
}

export default function ProjectUpload() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
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

  async function choose(file: File) {
    if (!slug) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const data = await uploadsApi.preview(slug, file);
      setPreview(data);
      // Start from the server's suggestions; every one of them is still
      // shown with its confidence and can be overridden.
      const initial: Record<string, string> = {};
      for (const [key, suggestion] of Object.entries(data.suggested_mapping)) {
        if (suggestion.column) initial[key] = suggestion.column;
      }
      setMapping(initial);
    } catch (caught) {
      setPreview(null);
      setError(caught instanceof Error ? caught.message : "Could not read that file.");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!slug || !preview) return;
    setBusy(true);
    setError(null);
    try {
      const contribution = await uploadsApi.commit(slug, {
        upload_token: preview.upload_token,
        mapping,
        mode: "shared",
        measurement_method: method || undefined,
        notes: notes || undefined,
      });
      setResult(contribution);
      setPreview(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not submit the file.");
    } finally {
      setBusy(false);
    }
  }

  if (!project) return <p className="muted">Loading…</p>;

  const isOwner = project.viewer_role === "owner";
  const wanted = [
    ...project.inputs.map((item) => ({ ...item.variable, role: "input" as const })),
    ...project.targets.map((item) => ({ ...item.variable, role: "target" as const })),
  ];
  const unmappedRequired = project.inputs.filter(
    (item) => item.required && !mapping[item.variable.key],
  );
  const anyTarget = project.targets.some((item) => mapping[item.variable.key]);
  const canSubmit = unmappedRequired.length === 0 && anyTarget && !busy;

  return (
    <section>
      <p className="eyebrow">
        <Link to={`/projects/${project.slug}`}>{project.title}</Link>
      </p>
      <h1>{isOwner ? "Add measurements" : "Contribute your measurements"}</h1>

      {!isOwner && (
        <div className="notice">
          <p>
            Sharing your file gives the project owner access to it, and gives{" "}
            <strong>you access to the model</strong> once they accept it. Your
            file is never shown to other contributors.
          </p>
          <p className="muted small">
            Contributing <em>without</em> sharing your data is planned — it
            improves the project's reference model without uploading anything,
            but does not unlock model access. It is not built yet (lot 5b).
          </p>
        </div>
      )}

      {/* 1 --------------------------------------------------------------- */}
      <h2>
        <span className="num">1</span> Your file
      </h2>
      <p className="muted">
        CSV, tab-separated text, or .xlsx. Semicolon separators, decimal commas
        and title rows above the header are handled automatically, as are Greek
        letters and units in column names.
      </p>
      <input
        type="file"
        accept=".csv,.txt,.tsv,.xlsx,.xlsm"
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

      {/* 2 --------------------------------------------------------------- */}
      {preview && (
        <>
          <h2>
            <span className="num">2</span> How it was read
          </h2>
          <p className="meta-line small">
            <span>{preview.filename}</span>
            <span>{preview.parse_report.n_rows} rows</span>
            <span>{preview.parse_report.n_columns} columns</span>
            {preview.parse_report.separator && (
              <span>separator “{preview.parse_report.separator}”</span>
            )}
            <span>decimal “{preview.parse_report.decimal}”</span>
            {preview.parse_report.sheet && <span>sheet {preview.parse_report.sheet}</span>}
          </p>
          {preview.parse_report.notes.map((note) => (
            <p key={note} className="muted small">
              {note}
            </p>
          ))}

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  {preview.columns.map((column) => (
                    <th key={column} scope="col">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.preview_rows.map((row, index) => (
                  <tr key={index}>
                    {preview.columns.map((column) => (
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
            <span className="num">3</span> Match your columns
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
                  const suggestion = preview.suggested_mapping[variable.key];
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
                          {preview.columns.map((column) => (
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
            </p>
          )}
          {!anyTarget && (
            <p className="muted">
              At least one target quantity must be matched — otherwise there is
              nothing to predict.
            </p>
          )}

          <h2>
            <span className="num">4</span> About these measurements
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

          <div className="cta-row">
            <button className="primary" type="button" disabled={!canSubmit} onClick={submit}>
              {busy ? "Submitting…" : isOwner ? "Add to my project" : "Submit contribution"}
            </button>
            <button type="button" className="ghost" onClick={() => setPreview(null)}>
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
              <strong>{result.n_rows} rows</strong> accepted from{" "}
              {result.original_filename}.{" "}
              {result.status === "pending"
                ? "It is now waiting for the project owner to review it. You get access to the model once they accept."
                : "It is part of your project."}
            </p>
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

          {result.validation && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Quantity</th>
                    <th scope="col">From your column</th>
                    <th scope="col">Range covered</th>
                  </tr>
                </thead>
                <tbody>
                  {result.validation.columns.map((column) => (
                    <tr key={`${column.variable_key}-${column.column}`}>
                      <td>{column.variable_key}</td>
                      <td>{column.column}</td>
                      <td>
                        {column.min} → {column.max}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
