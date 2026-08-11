/* The project page.
 *
 * What exists now is the declaration: inputs, targets, and who the viewer is
 * to this project. The validity-domain chart, the version timeline and the
 * model card are lot 3, and the sections below say so rather than being
 * silently absent — the build order is "each finished lot leaves a working
 * site", and a page that hides its own incompleteness undercuts that.
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ENGINE_LABELS, projects as projectsApi, type ProjectDetail as Detail } from "../lib/api";

function priorLabel(sign: number | null): string {
  if (sign === null) return "—";
  return sign < 0 ? "should not decrease the target" : "should not increase the target";
}

function rangeLabel(min: number | null, max: number | null): string {
  if (min === null && max === null) return "not declared";
  return `${min ?? "?"} → ${max ?? "?"}`;
}

export default function ProjectDetail() {
  const { slug } = useParams<{ slug: string }>();
  const [project, setProject] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    projectsApi
      .get(slug)
      .then(setProject)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load."),
      );
  }, [slug]);

  if (error) {
    return (
      <section>
        <h1>Project</h1>
        <p className="error" role="alert">
          {error}
        </p>
        <p>
          <Link to="/projects">Back to projects</Link>
        </p>
      </section>
    );
  }
  if (!project) return <p className="muted">Loading…</p>;

  return (
    <section>
      <p className="eyebrow">
        {[project.material, project.process].filter(Boolean).join(" · ") ||
          "no domain declared"}
      </p>
      <h1>{project.title}</h1>

      <p className="meta-line">
        {project.owner_name && <span>{project.owner_name}</span>}
        {project.licence && <span>{project.licence}</span>}
        <span>{project.n_rows_total} rows</span>
        <span>
          {project.n_contributors} contributor{project.n_contributors === 1 ? "" : "s"}
        </span>
        <span>
          {project.latest_version === null ? "no model yet" : `v${project.latest_version}`}
        </span>
        {project.status === "draft" && <span className="badge">draft</span>}
        {project.viewer_role && <span className="badge">you: {project.viewer_role}</span>}
      </p>

      {project.description && <p className="lead">{project.description}</p>}

      <h2>Inputs</h2>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Quantity</th>
              <th scope="col">Unit</th>
              <th scope="col">Expected range</th>
              <th scope="col">Physical prior</th>
            </tr>
          </thead>
          <tbody>
            {project.inputs.map((item) => (
              <tr key={item.variable.key}>
                <td className="muted">{item.position + 1}</td>
                <td>
                  <strong>{item.variable.display_name}</strong>
                  {item.variable.symbol && (
                    <span className="muted"> {item.variable.symbol}</span>
                  )}
                  <br />
                  <code className="small">{item.variable.key}</code>
                </td>
                <td>{item.unit ?? "—"}</td>
                <td>{rangeLabel(item.expected_min, item.expected_max)}</td>
                <td className="small">{priorLabel(item.penalised_sign)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Targets</h2>
      <ul className="chip-list">
        {project.targets.map((item) => (
          <li key={item.variable.key} className="chip static">
            {item.variable.display_name}
            {item.unit && <span className="muted"> · {item.unit}</span>}
          </li>
        ))}
      </ul>

      <h2>Model</h2>
      <div className="notice">
        <p>
          Main engine: <strong>{ENGINE_LABELS[project.main_engine]}</strong>. A
          linear reference model is trained alongside it, so that contributors
          who improve the project without sharing their data still count.
        </p>
        <p>
          <strong>Not built yet.</strong> Uploading data and fitting a model is
          lot 2; the validity-domain chart, version timeline and model card are
          lot 3. See <code>ROADMAP.md</code>.
        </p>
      </div>

      {project.viewer_can_read_raw_data && (
        <p className="muted small">
          You own this project, so you will be able to read every file
          contributed to it. Contributors can see that this access exists.
        </p>
      )}
    </section>
  );
}
