/* How well one project fits the file you dropped.
 *
 * The rule this card exists to obey: **a compatibility score, never a boolean**
 * (ARCHITECTURE.md §7). "4/4 inputs, one by approximate match — please check"
 * is honest; a green tick is not, because a column matched to the wrong
 * quantity fits a model to the wrong thing and nothing looks broken afterwards.
 *
 * The second thing it has to get right is the domain fraction. A low fraction
 * means your measurements sit outside the range this project has data for —
 * and that is *not* a reason to stay away. It is the mark of a contribution
 * that would extend the model's validity domain, which is the most valuable
 * kind there is. Presented as a warning it would drive away exactly the data
 * the platform most needs, so it is presented as an opportunity.
 */

import { Link } from "react-router-dom";

import type { ProjectMatch } from "../lib/api";

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export default function MatchCard({ match }: { match: ProjectMatch }) {
  const { project } = match;
  const blocked = match.missing_required_inputs.length > 0;
  const extendsDomain =
    match.fraction_in_domain !== null && match.fraction_in_domain < 0.5;

  return (
    <li className="project-card match-card">
      <div className="page-head">
        <h3>
          <Link to={`/projects/${project.slug}`}>{project.title}</Link>
        </h3>
        <span className="match-score" title="Weighted across the parts below">
          {percent(match.score)}
        </span>
      </div>

      <p className="eyebrow">
        {[project.material, project.process].filter(Boolean).join(" · ") ||
          "no domain declared"}
      </p>

      <p className="meta-line small">
        <span>{project.n_rows_total} rows</span>
        <span>
          {project.n_contributors} contributor{project.n_contributors === 1 ? "" : "s"}
        </span>
        <span>
          {project.latest_version === null ? "no model yet" : `v${project.latest_version}`}
        </span>
      </p>

      <ul className="match-facts small">
        <li>
          <strong>
            {match.inputs_matched}/{match.inputs_total} inputs
          </strong>{" "}
          matched
          {match.inputs_approximate > 0 && (
            <>
              {" — "}
              <span className="warn-text">
                {match.inputs_approximate} by approximate match, please check
              </span>
            </>
          )}
        </li>
        <li>
          <strong>
            {match.matched_targets.length}/{match.targets_total} targets
          </strong>{" "}
          {match.matched_targets.length === 0
            ? "— your file predicts nothing this project models, so it cannot train it"
            : "present in your file"}
        </li>
        {match.fraction_in_domain !== null ? (
          <li>
            <strong>{percent(match.fraction_in_domain)}</strong> of your rows
            ({match.rows_in_domain}/{match.rows_scanned}) fall inside the range
            this project has data for
          </li>
        ) : (
          <li className="muted">
            This project holds no data yet, so there is no domain to compare
            against.
          </li>
        )}
      </ul>

      {blocked && (
        <p className="muted small">
          Missing required input{match.missing_required_inputs.length === 1 ? "" : "s"}:{" "}
          {match.missing_required_inputs.map((key) => (
            <code key={key} className="small">
              {key}
            </code>
          ))}
          . Your file cannot be contributed here as it stands — unless one of
          your columns is this quantity under a name the registry does not know
          yet.
        </p>
      )}

      {match.unit_conflicts.length > 0 && (
        <p className="warn-text small">
          Unit mismatch — {match.unit_conflicts.join("; ")}. That is the
          strongest sign a name match is wrong.
        </p>
      )}

      {extendsDomain && (
        <p className="reading valuable small">
          <strong>Most of your data is outside this project's range.</strong>{" "}
          That makes it more valuable here, not less — measurements from a
          regime nobody has covered are what extends a model's validity domain.
        </p>
      )}
    </li>
  );
}
