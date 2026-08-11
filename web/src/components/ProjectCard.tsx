import { Link } from "react-router-dom";

import type { ProjectSummary } from "../lib/api";

export default function ProjectCard({ project }: { project: ProjectSummary }) {
  return (
    <li className="project-card">
      <h3>
        <Link to={`/projects/${project.slug}`}>{project.title}</Link>
      </h3>
      <p className="eyebrow">
        {[project.material, project.process].filter(Boolean).join(" · ") ||
          "no domain declared"}
      </p>
      <p className="meta-line small">
        {project.owner_name && <span>{project.owner_name}</span>}
        <span>{project.n_rows_total} rows</span>
        <span>
          {project.n_contributors} contributor{project.n_contributors === 1 ? "" : "s"}
        </span>
        <span>
          {project.latest_version === null ? "no model yet" : `v${project.latest_version}`}
        </span>
        {project.status === "draft" && <span className="badge">draft</span>}
      </p>
    </li>
  );
}
