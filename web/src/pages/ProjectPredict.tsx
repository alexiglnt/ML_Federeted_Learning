/* Using the model.
 *
 * Behind the same gate as the coefficients, and for the same reason: being
 * able to query a model without limit is having the model. A visitor who has
 * not contributed is told what to do about it rather than shown a dead form.
 *
 * The out-of-domain warning is the part that matters. A prediction outside the
 * range the model has data for is answered — the model is still the best
 * estimate available — but it is a different kind of claim, and the server
 * says so against the *covered* range rather than the declared one. The form
 * hints at it while typing; the answer that counts comes back with the
 * prediction.
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  ENGINE_LABELS,
  modelsApi,
  projects as projectsApi,
  type ModelTrack,
  type ModelVersionOut,
  type PredictResponse,
  type ProjectDetail,
  type ProjectInputOut,
} from "../lib/api";

/** Somewhere sensible to start: the middle of where the data actually is,
 *  falling back to the middle of the declared range. A form that opens on
 *  zeroes invites a first prediction that is pure extrapolation. */
function startingValue(item: ProjectInputOut): string {
  const pairs: [number | null, number | null][] = [
    [item.observed_min, item.observed_max],
    [item.expected_min, item.expected_max],
  ];
  for (const [low, high] of pairs) {
    if (low !== null && high !== null) {
      return String(Math.round(((low + high) / 2) * 1000) / 1000);
    }
  }
  return "";
}

function outsideCovered(item: ProjectInputOut, raw: string): boolean {
  const value = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(value)) return false;
  if (item.observed_min === null || item.observed_max === null) return false;
  return value < item.observed_min || value > item.observed_max;
}

export default function ProjectPredict() {
  const { slug } = useParams<{ slug: string }>();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [versions, setVersions] = useState<ModelVersionOut[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [track, setTrack] = useState<ModelTrack>("main");
  const [version, setVersion] = useState<string>("");
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!slug) return;
    projectsApi
      .get(slug)
      .then((detail) => {
        setProject(detail);
        const initial: Record<string, string> = {};
        for (const item of detail.inputs) initial[item.variable.key] = startingValue(item);
        setValues(initial);
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load the project."),
      );
    modelsApi
      .versions(slug)
      .then(setVersions)
      .catch(() => setVersions([]));
  }, [slug]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!slug || !project) return;

    const parsed: Record<string, number> = {};
    for (const item of project.inputs) {
      const raw = values[item.variable.key] ?? "";
      const value = Number(raw);
      if (raw.trim() === "" || !Number.isFinite(value)) {
        setError(`${item.variable.display_name} needs a number.`);
        return;
      }
      parsed[item.variable.key] = value;
    }

    setBusy(true);
    setError(null);
    try {
      setResult(
        await modelsApi.predict(slug, {
          values: parsed,
          track,
          version: version ? Number(version) : null,
        }),
      );
    } catch (caught) {
      setResult(null);
      setError(caught instanceof Error ? caught.message : "The prediction failed.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !project) {
    return (
      <section>
        <h1>Predict</h1>
        <p className="error" role="alert">
          {error}
        </p>
      </section>
    );
  }
  if (!project) return <p className="muted">Loading…</p>;

  /* The gate ---------------------------------------------------------- */
  if (!project.viewer_can_use_model) {
    return (
      <section>
        <p className="eyebrow">
          <Link to={`/projects/${project.slug}`}>{project.title}</Link>
        </p>
        <h1>Use the model</h1>
        <div className="notice">
          <p>
            <strong>This model is not open to you yet.</strong> Its scores are
            public so you can judge whether it is worth having — the model
            itself is the counterpart of contributing data.
          </p>
          <p>
            Contribute measurements of the same quantities and, once the owner
            accepts them, prediction and export unlock here.
          </p>
        </div>
        <div className="cta-row">
          <Link to={`/projects/${project.slug}/upload`} className="primary button-like">
            Contribute my measurements
          </Link>
          <Link to={`/projects/${project.slug}`} className="ghost button-like">
            Back to the project
          </Link>
        </div>
      </section>
    );
  }

  if (project.latest_version === null) {
    return (
      <section>
        <p className="eyebrow">
          <Link to={`/projects/${project.slug}`}>{project.title}</Link>
        </p>
        <h1>Use the model</h1>
        <p className="muted">
          This project has no trained model yet. One is fitted as soon as it
          holds accepted measurements.
        </p>
      </section>
    );
  }

  const hintedOutside = project.inputs.filter((item) =>
    outsideCovered(item, values[item.variable.key] ?? ""),
  );

  return (
    <section>
      <p className="eyebrow">
        <Link to={`/projects/${project.slug}`}>{project.title}</Link>
      </p>
      <h1>Use the model</h1>
      <p className="lead">
        One set of cutting parameters in, one prediction per target out.
      </p>

      <form className="predict-form" onSubmit={submit}>
        <h2>Inputs</h2>
        <div className="predict-grid">
          {project.inputs.map((item) => {
            const key = item.variable.key;
            const outside = outsideCovered(item, values[key] ?? "");
            return (
              <div className="field-row" key={key}>
                <label htmlFor={`in-${key}`}>
                  {item.variable.display_name}
                  {item.unit && <span className="hint"> {item.unit}</span>}
                </label>
                <input
                  id={`in-${key}`}
                  type="number"
                  step="any"
                  inputMode="decimal"
                  value={values[key] ?? ""}
                  onChange={(e) =>
                    setValues((current) => ({ ...current, [key]: e.target.value }))
                  }
                  aria-describedby={`hint-${key}`}
                />
                <span id={`hint-${key}`} className={outside ? "hint warn-text" : "hint"}>
                  {item.observed_min === null || item.observed_max === null
                    ? "no data for this input yet"
                    : outside
                      ? `outside the data (${item.observed_min} → ${item.observed_max})`
                      : `data covers ${item.observed_min} → ${item.observed_max}`}
                </span>
              </div>
            );
          })}
        </div>

        <h2>Which model</h2>
        <div className="predict-grid">
          <div className="field-row">
            <label htmlFor="track">Track</label>
            <select
              id="track"
              value={track}
              onChange={(e) => setTrack(e.target.value as ModelTrack)}
            >
              <option value="main">Main — {ENGINE_LABELS[project.main_engine]}</option>
              <option value="reference">Reference — linear baseline</option>
            </select>
            <span className="hint">
              The reference model is the one every contributor feeds, including
              those who never uploaded a file. Worth comparing: if the main
              engine does not beat it, that is a finding.
            </span>
          </div>
          <div className="field-row">
            <label htmlFor="version">Version</label>
            <select
              id="version"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
            >
              <option value="">Latest (v{project.latest_version})</option>
              {versions.map((item) => (
                <option key={item.number} value={String(item.number)}>
                  v{item.number} — {new Date(item.created_at).toLocaleDateString()}
                </option>
              ))}
            </select>
            <span className="hint">
              Older versions stay queryable so a published number can be
              reproduced.
            </span>
          </div>
        </div>

        {hintedOutside.length > 0 && (
          <p className="muted small">
            {hintedOutside.length} input
            {hintedOutside.length === 1 ? " sits" : "s sit"} outside the range the
            model has data for. The prediction will still be given, as an
            extrapolation.
          </p>
        )}

        <div className="cta-row">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Predicting…" : "Predict"}
          </button>
        </div>
      </form>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <>
          <h2>Prediction</h2>
          {/* The warning goes above the numbers on purpose. Underneath them it
              would be read after the reader has already believed the figure. */}
          {result.out_of_domain.length > 0 && (
            <div className="notice warn-notice" role="alert">
              <p>
                <strong>This is an extrapolation.</strong>
              </p>
              <ul className="warning-list">
                {result.out_of_domain.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="model-grid">
            {result.predictions.map((prediction) => (
              <article className="model-card" key={prediction.target_key}>
                <h3>{prediction.target_name}</h3>
                <p className="prediction-value">
                  {Math.round(prediction.value * 1000) / 1000}
                  {prediction.target_unit && (
                    <span className="muted"> {prediction.target_unit}</span>
                  )}
                </p>
                <p className="meta-line small">
                  <span>{ENGINE_LABELS[prediction.engine]}</span>
                  <span>{prediction.track} track</span>
                  <span>v{result.version}</span>
                </p>
              </article>
            ))}
          </div>

          <p className="muted small">
            A research tool. Read the scores on the project page before acting
            on any of this — a model fitted on a handful of conditions is a
            hypothesis, not a specification.
          </p>
        </>
      )}
    </section>
  );
}
