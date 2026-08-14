import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

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
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [mine, setMine] = useState<ProjectSummary[]>([]);
  const [loadingMine, setLoadingMine] = useState(true);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [reviewQueue, setReviewQueue] = useState<MyReviewQueueItem[] | null>(null);
  const [contributions, setContributions] = useState<MyContribution[] | null>(null);
  const [access, setAccess] = useState<MyAccess[] | null>(null);

  const [editingProfile, setEditingProfile] = useState(false);
  const [fullName, setFullName] = useState("");
  const [institution, setInstitution] = useState("");
  const [country, setCountry] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);

  const [changingPassword, setChangingPassword] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSaved, setPasswordSaved] = useState(false);

  function startEditingProfile() {
    setFullName(user?.full_name ?? "");
    setInstitution(user?.institution ?? "");
    setCountry(user?.country ?? "");
    setProfileError(null);
    setProfileSaved(false);
    setEditingProfile(true);
  }

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    setProfileBusy(true);
    setProfileError(null);
    try {
      await meApi.updateProfile({
        full_name: fullName,
        institution,
        country,
      });
      await refresh();
      setEditingProfile(false);
      setProfileSaved(true);
    } catch (caught) {
      setProfileError(caught instanceof Error ? caught.message : "Could not save.");
    } finally {
      setProfileBusy(false);
    }
  }

  async function savePassword(event: React.FormEvent) {
    event.preventDefault();
    setPasswordBusy(true);
    setPasswordError(null);
    try {
      await meApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setChangingPassword(false);
      setPasswordSaved(true);
    } catch (caught) {
      setPasswordError(caught instanceof Error ? caught.message : "Could not change it.");
    } finally {
      setPasswordBusy(false);
    }
  }

  async function deleteAccount(event: React.FormEvent) {
    event.preventDefault();
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await meApi.deleteAccount(deletePassword);
      await refresh();
      navigate("/");
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : "Could not delete the account.");
      setDeleteBusy(false);
    }
  }

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

      {!editingProfile ? (
        <>
          <dl className="key-values">
            <dt>Name</dt>
            <dd>{user.full_name}</dd>
            <dt>Email</dt>
            <dd>{user.email}</dd>
            <dt>Institution</dt>
            <dd>{user.institution ?? "—"}</dd>
            <dt>Country</dt>
            <dd>{user.country ?? "—"}</dd>
          </dl>
          {profileSaved && <p className="muted small" role="status">Saved.</p>}
          <div className="cta-row">
            <button type="button" className="ghost" onClick={startEditingProfile}>
              Edit profile
            </button>
            {!changingPassword && (
              <button type="button" className="ghost" onClick={() => setChangingPassword(true)}>
                Change password
              </button>
            )}
          </div>
        </>
      ) : (
        <form onSubmit={saveProfile}>
          <div className="field-row wide">
            <label htmlFor="full_name">Name</label>
            <input
              id="full_name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              minLength={1}
            />
          </div>
          <div className="field-row wide">
            <label htmlFor="institution">Institution</label>
            <input
              id="institution"
              value={institution}
              onChange={(e) => setInstitution(e.target.value)}
            />
          </div>
          <div className="field-row wide">
            <label htmlFor="country">Country</label>
            <input id="country" value={country} onChange={(e) => setCountry(e.target.value)} />
          </div>
          {profileError && (
            <p className="error" role="alert">
              {profileError}
            </p>
          )}
          <div className="cta-row">
            <button className="primary" type="submit" disabled={profileBusy}>
              {profileBusy ? "Saving…" : "Save"}
            </button>
            <button type="button" className="ghost" onClick={() => setEditingProfile(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {changingPassword && (
        <form onSubmit={savePassword}>
          <div className="field-row wide">
            <label htmlFor="current_password">Current password</label>
            <input
              id="current_password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>
          <div className="field-row wide">
            <label htmlFor="new_password">New password</label>
            <input
              id="new_password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={10}
              autoComplete="new-password"
            />
            <span className="hint">At least 10 characters.</span>
          </div>
          {passwordError && (
            <p className="error" role="alert">
              {passwordError}
            </p>
          )}
          <div className="cta-row">
            <button className="primary" type="submit" disabled={passwordBusy}>
              {passwordBusy ? "Saving…" : "Change password"}
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setChangingPassword(false);
                setCurrentPassword("");
                setNewPassword("");
                setPasswordError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {!changingPassword && passwordSaved && (
        <p className="muted small" role="status">
          Password changed.
        </p>
      )}

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

      <div className="notice danger-zone">
        <h2>Danger zone</h2>
        {!loadingMine && mine.length > 0 ? (
          <p>
            You still own {mine.length} project{mine.length > 1 ? "s" : ""}. Delete
            or hand each one off from its settings page before you can close
            your account.
          </p>
        ) : (
          <>
            <p>
              Closes your account. Your name and email are replaced and your
              password is locked — you can no longer sign in. Contributions
              you made to other people&rsquo;s projects stay recorded, the
              same as a rejected contribution does: removing them would
              silently change the history behind a model someone else
              published.
            </p>
            {!confirmingDelete ? (
              <button type="button" className="danger" onClick={() => setConfirmingDelete(true)}>
                Delete my account
              </button>
            ) : (
              <form onSubmit={deleteAccount} className="field-row wide">
                <label htmlFor="delete-password">Confirm your password</label>
                <input
                  id="delete-password"
                  type="password"
                  value={deletePassword}
                  onChange={(e) => setDeletePassword(e.target.value)}
                  required
                  autoComplete="current-password"
                />
                {deleteError && (
                  <p className="error" role="alert">
                    {deleteError}
                  </p>
                )}
                <div className="cta-row">
                  <button className="danger" type="submit" disabled={deleteBusy}>
                    {deleteBusy ? "Deleting…" : "Delete permanently"}
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setConfirmingDelete(false);
                      setDeletePassword("");
                      setDeleteError(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </section>
  );
}
