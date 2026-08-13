import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import ProjectCard from "../components/ProjectCard";
import {
  me as meApi,
  projects as projectsApi,
  type MyAccess,
  type MyContribution,
  type MyReviewQueueItem,
  type ProjectSummary,
} from "../lib/api";
import { useAuth } from "../lib/auth";

function statusBadge(status: MyContribution["status"]) {
  if (status === "pending") return <span className="badge warn">pending</span>;
  if (status === "accepted") return <span className="badge">accepted</span>;
  if (status === "rejected") return <span className="badge danger">rejected</span>;
  return <span className="badge muted-badge">withdrawn</span>;
}

export default function Me() {
  const { user } = useAuth();
  const [mine, setMine] = useState<ProjectSummary[]>([]);
  const [loadingMine, setLoadingMine] = useState(true);

  const [reviewQueue, setReviewQueue] = useState<MyReviewQueueItem[] | null>(null);
  const [contributions, setContributions] = useState<MyContribution[] | null>(null);
  const [access, setAccess] = useState<MyAccess[] | null>(null);

  useEffect(() => {
    projectsApi
      .mine()
      .then(setMine)
      .catch(() => setMine([]))
      .finally(() => setLoadingMine(false));

    // Loaded independently so one failing section does not blank the page.
    meApi.reviewQueue().then(setReviewQueue).catch(() => setReviewQueue([]));
    meApi.contributions().then(setContributions).catch(() => setContributions([]));
    meApi.access().then(setAccess).catch(() => setAccess([]));
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
      {loadingMine && <p className="muted">Loading…</p>}
      {!loadingMine && mine.length === 0 && (
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

      {reviewQueue && reviewQueue.length > 0 && (
        <>
          <h2>Awaiting my review</h2>
          <p className="muted small">
            Pending contributions across every project you own. Decide on each from
            its project page, where the full transfer and refit scores are shown.
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Project</th>
                  <th scope="col">Contributor</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Rows</th>
                  <th scope="col">Submitted</th>
                </tr>
              </thead>
              <tbody>
                {reviewQueue.map((item) => (
                  <tr key={item.contribution_id}>
                    <td>
                      <Link to={`/projects/${item.project_slug}`}>{item.project_title}</Link>
                    </td>
                    <td>{item.contributor_name}</td>
                    <td>{item.mode === "federated" ? "summary statistics" : "shared file"}</td>
                    <td>{item.n_rows}</td>
                    <td>{new Date(item.submitted_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Contributions I&rsquo;ve made</h2>
      {contributions === null && <p className="muted">Loading…</p>}
      {contributions?.length === 0 && (
        <p className="muted">
          None yet. Open a project and use its upload page to contribute measurements.
        </p>
      )}
      {contributions && contributions.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Project</th>
                <th scope="col">Status</th>
                <th scope="col">Mode</th>
                <th scope="col">Rows</th>
                <th scope="col">Submitted</th>
                <th scope="col">Review note</th>
              </tr>
            </thead>
            <tbody>
              {contributions.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link to={`/projects/${item.project_slug}`}>{item.project_title}</Link>
                  </td>
                  <td>{statusBadge(item.status)}</td>
                  <td>{item.mode === "federated" ? "summary statistics" : "shared file"}</td>
                  <td>{item.n_rows}</td>
                  <td>{new Date(item.submitted_at).toLocaleDateString()}</td>
                  <td>{item.review_note ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Projects I can access</h2>
      {access === null && <p className="muted">Loading…</p>}
      {access?.length === 0 && (
        <p className="muted">
          None yet. Model access follows an accepted, shared contribution — a
          federated (summary-only) one does not unlock it.
        </p>
      )}
      {access && access.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Project</th>
                <th scope="col">Role</th>
                <th scope="col">Granted</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {access.map((item) => (
                <tr key={item.project_slug}>
                  <td>
                    <Link to={`/projects/${item.project_slug}`}>{item.project_title}</Link>
                  </td>
                  <td>
                    <span className={`badge${item.role === "viewer" ? " muted-badge" : ""}`}>
                      {item.role}
                    </span>
                  </td>
                  <td>{new Date(item.granted_at).toLocaleDateString()}</td>
                  <td>
                    <Link to={`/projects/${item.project_slug}/predict`} className="ghost tiny-button">
                      Predict
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
