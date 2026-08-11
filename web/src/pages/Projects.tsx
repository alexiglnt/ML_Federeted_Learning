import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ProjectCard from "../components/ProjectCard";
import { projects as projectsApi, type ProjectSummary } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Projects() {
  const { user } = useAuth();
  const [rows, setRows] = useState<ProjectSummary[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      projectsApi
        .list(query || undefined)
        .then((data) => {
          if (!cancelled) setRows(data);
        })
        .catch((caught: unknown) => {
          if (!cancelled)
            setError(caught instanceof Error ? caught.message : "Could not load.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  return (
    <section>
      <div className="page-head">
        <h1>Projects</h1>
        {user && (
          <Link to="/projects/new" className="primary button-like">
            Create a project
          </Link>
        )}
      </div>

      <div className="field-row">
        <label htmlFor="q">Search by title, material or process</label>
        <input
          id="q"
          value={query}
          placeholder="titanium, turning, residual stress…"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && <p className="muted">Loading…</p>}
      {!loading && rows.length === 0 && (
        <p className="muted">
          {query ? `Nothing matches “${query}”.` : "No projects yet."}
        </p>
      )}

      <ul className="project-list">
        {rows.map((project) => (
          <ProjectCard key={project.id} project={project} />
        ))}
      </ul>

      <div className="notice">
        <h2>Discovery is still basic</h2>
        <p>
          This is a plain title search. Lot 4 replaces it with faceted filtering
          — target quantity, material, process, input variables, size — and a
          reverse search where you drop your own file first and projects are
          ranked by how many of your columns they match and how much of your
          data falls inside their validity domain.
        </p>
      </div>
    </section>
  );
}
