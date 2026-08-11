import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ProjectCard from "../components/ProjectCard";
import { projects as projectsApi, type ProjectSummary } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Me() {
  const { user } = useAuth();
  const [mine, setMine] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    projectsApi
      .mine()
      .then(setMine)
      .catch(() => setMine([]))
      .finally(() => setLoading(false));
  }, []);

  if (!user) return null;

  return (
    <section>
      <div className="page-head">
        <h1>My work</h1>
        <Link to="/projects/new" className="primary button-like">
          Create a project
        </Link>
      </div>

      <dl className="key-values">
        <dt>Name</dt>
        <dd>{user.full_name}</dd>
        <dt>Email</dt>
        <dd>{user.email}</dd>
        <dt>Institution</dt>
        <dd>{user.institution ?? "—"}</dd>
      </dl>

      <h2>Projects I own</h2>
      {loading && <p className="muted">Loading…</p>}
      {!loading && mine.length === 0 && (
        <p className="muted">
          None yet. <Link to="/projects/new">Create one</Link> by declaring the
          quantities you measure.
        </p>
      )}
      <ul className="project-list">
        {mine.map((project) => (
          <ProjectCard key={project.id} project={project} />
        ))}
      </ul>

      <div className="notice">
        <h2>Not built yet</h2>
        <p>
          This will also list the contributions you have made, the models you
          have access to, and any contributions awaiting your review. Those
          arrive with lots 2 and 5.
        </p>
      </div>
    </section>
  );
}
