/* The version history, and what made the model move.
 *
 * The lineage is the point: a version that says "+12 rows from TU Wien, R²
 * 0.78 → 0.81" answers the question this platform exists to answer, where a
 * bare list of version numbers answers nothing.
 */

import { useState } from "react";

import type { ModelVersionOut } from "../lib/api";

function delta(current: number | null, previous: number | null | undefined): string | null {
  if (current === null || previous === null || previous === undefined) return null;
  const change = current - previous;
  if (Math.abs(change) < 0.0005) return "no change";
  return `${change > 0 ? "↑" : "↓"} ${Math.abs(change).toFixed(3)}`;
}

export default function VersionTimeline({ versions }: { versions: ModelVersionOut[] }) {
  const [open, setOpen] = useState<number | null>(versions[0]?.number ?? null);

  if (versions.length === 0) {
    return <p className="muted">No model has been trained yet.</p>;
  }

  return (
    <ol className="timeline">
      {versions.map((version, index) => {
        // versions arrive newest first, so the previous one is the next entry.
        const older = versions[index + 1];
        const change = delta(version.headline_r2, older?.headline_r2 ?? null);
        const expanded = open === version.number;
        return (
          <li key={version.number} className="timeline-item">
            <button
              type="button"
              className="timeline-head"
              aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : version.number)}
            >
              <span className="version-number">v{version.number}</span>
              <span className="timeline-facts">
                <span>{new Date(version.created_at).toLocaleDateString()}</span>
                <span>{version.n_rows_total} rows</span>
                <span>
                  {version.n_contributions} contribution
                  {version.n_contributions === 1 ? "" : "s"}
                </span>
                <span>
                  R²{" "}
                  {version.headline_r2 === null ? "—" : version.headline_r2.toFixed(3)}
                </span>
                {change && <span className="badge">{change}</span>}
              </span>
              <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
            </button>

            {expanded && (
              <div className="timeline-body">
                <h4>Data in this version</h4>
                {version.sources.length === 0 ? (
                  <p className="muted small">No lineage recorded.</p>
                ) : (
                  <ul className="source-list">
                    {version.sources.map((source) => (
                      <li key={source.contribution_id}>
                        <strong>{source.contributor_name}</strong> — {source.n_rows} rows
                        {source.measurement_method && ` · ${source.measurement_method}`}
                        {source.mode === "federated" && " · summary statistics only"}
                      </li>
                    ))}
                  </ul>
                )}

                <h4>Models fitted</h4>
                <div className="table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">Track</th>
                        <th scope="col">Target</th>
                        <th scope="col">Engine</th>
                        <th scope="col">R² across labs</th>
                        <th scope="col">R² out of sample</th>
                      </tr>
                    </thead>
                    <tbody>
                      {version.models.map((model) => (
                        <tr key={`${model.track}-${model.target_key}`}>
                          <td>{model.track}</td>
                          <td>{model.target_name}</td>
                          <td>{model.engine}</td>
                          <td>
                            {model.metrics.r2_leave_one_lab_out?.toFixed(3) ?? "—"}
                          </td>
                          <td>{model.metrics.r2_cv?.toFixed(3) ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
