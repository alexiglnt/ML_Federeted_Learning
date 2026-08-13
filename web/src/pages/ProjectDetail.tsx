/* The project page.
 *
 * It answers, in order: what needs my decision, what is this project about,
 * where can its model be believed, how good is it, what made it move, and who
 * made it. The validity domain comes before the scores on purpose — a strong
 * R² over a range that does not include your cutting conditions is not a useful
 * model, and reading the score first invites exactly that mistake.
 *
 * The review queue sits above all of it for the owner, because it is the only
 * thing on the page that someone is waiting on. There is no notification system
 * (see ROADMAP.md), so the project page is the only place a pending
 * contribution is ever seen.
 *
 * What the viewer may do is decided by the server and carried on the project
 * (`viewer_can_use_model`, `viewer_can_read_raw_data`) rather than re-derived
 * here, so the front end cannot drift into a subtly different reading of the
 * permission matrix than the one the API enforces.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import AccessLog from "../components/AccessLog";
import ContributorList from "../components/ContributorList";
import DomainBar from "../components/DomainBar";
import ModelCard from "../components/ModelCard";
import ReviewCard from "../components/ReviewCard";
import VersionTimeline from "../components/VersionTimeline";
import {
  ENGINE_LABELS,
  modelsApi,
  projects as projectsApi,
  uploads as uploadsApi,
  type AccessLogEntry,
  type ContributionOut,
  type ContributorOut,
  type ModelVersionOut,
  type ProjectDetail as Detail,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { saveFile } from "../lib/download";

function priorLabel(sign: number | null): string {
  if (sign === null) return "—";
  return sign < 0 ? "should not decrease the target" : "should not increase the target";
}

export default function ProjectDetail() {
  const { slug } = useParams<{ slug: string }>();
  const { user } = useAuth();
  const [project, setProject] = useState<Detail | null>(null);
  const [contributions, setContributions] = useState<ContributionOut[]>([]);
  const [contributors, setContributors] = useState<ContributorOut[]>([]);
  const [accessLog, setAccessLog] = useState<AccessLogEntry[]>([]);
  const [versions, setVersions] = useState<ModelVersionOut[]>([]);
  const [training, setTraining] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadPublic = useCallback((forSlug: string) => {
    projectsApi.get(forSlug).then(setProject).catch(() => undefined);
    projectsApi.contributors(forSlug).then(setContributors).catch(() => setContributors([]));
    modelsApi.versions(forSlug).then(setVersions).catch(() => setVersions([]));
  }, []);

  const loadPrivate = useCallback((forSlug: string) => {
    // Both endpoints return everything to the owner and only the caller's own
    // rows to anyone else, so there is nothing to gate on the client.
    uploadsApi.contributions(forSlug).then(setContributions).catch(() => setContributions([]));
    uploadsApi.accessLog(forSlug).then(setAccessLog).catch(() => setAccessLog([]));
  }, []);

  /** Wait for a queued retrain, then refresh everything it touched. */
  const followJob = useCallback(
    async (forSlug: string, jobId: number) => {
      for (let attempt = 0; attempt < 90; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        try {
          const state = await modelsApi.job(forSlug, jobId);
          if (state.status === "done") {
            setTraining(state.log ?? "Retrained.");
            loadPublic(forSlug);
            return;
          }
          if (state.status === "failed") {
            setTraining(`Retraining failed: ${state.error}`);
            loadPublic(forSlug);
            return;
          }
        } catch {
          return;
        }
      }
      setTraining("Still retraining — reload the page in a moment.");
    },
    [loadPublic],
  );

  async function retrain() {
    if (!slug) return;
    setTraining("Training…");
    try {
      const job = await modelsApi.train(slug);
      await followJob(slug, job.id);
    } catch (caught) {
      setTraining(caught instanceof Error ? caught.message : "Could not start training.");
    }
  }

  async function decide(
    contribution: ContributionOut,
    decision: "accept" | "reject",
    note: string,
  ) {
    if (!slug) return;
    setBusyId(contribution.id);
    setFileError(null);
    try {
      const result = await uploadsApi.review(slug, contribution.id, decision, note);
      setTraining(
        decision === "accept"
          ? `Accepted. ${result.access_granted ? "They now have access to the model. " : ""}Retraining…`
          : `Rejected.${result.access_revoked ? " Their model access was removed." : ""}`,
      );
      loadPrivate(slug);
      loadPublic(slug);
      if (result.training_job) await followJob(slug, result.training_job.id);
    } catch (caught) {
      setFileError(caught instanceof Error ? caught.message : "Could not record the decision.");
    } finally {
      setBusyId(null);
    }
  }

  async function withdraw(contribution: ContributionOut) {
    if (!slug) return;
    setBusyId(contribution.id);
    setFileError(null);
    try {
      const result = await uploadsApi.withdraw(slug, contribution.id);
      setTraining(
        result.access_revoked
          ? "Withdrawn. Your data is out of the model, and your access to it has gone with it."
          : "Withdrawn.",
      );
      loadPrivate(slug);
      loadPublic(slug);
      if (result.training_job) await followJob(slug, result.training_job.id);
    } catch (caught) {
      setFileError(caught instanceof Error ? caught.message : "Could not withdraw.");
    } finally {
      setBusyId(null);
    }
  }

  async function exportModel() {
    if (!slug) return;
    setFileError(null);
    try {
      const { blob } = await modelsApi.export(slug);
      saveFile(blob, `${slug}-model-v${project?.latest_version ?? "latest"}.json`);
    } catch (caught) {
      setFileError(caught instanceof Error ? caught.message : "Could not export the model.");
    }
  }

  /** Checked live, on request, from the card itself — not cached here the
   *  way the rest of this page's data is, because the answer depends on the
   *  *current* accepted pool and would go stale the moment another pending
   *  contribution is decided. See ARCHITECTURE.md §5.7. */
  function checkPoolability(contribution: ContributionOut) {
    if (!slug) return Promise.reject(new Error("No project loaded."));
    return uploadsApi.poolability(slug, contribution.id);
  }

  async function downloadFile(contribution: ContributionOut) {
    if (!slug) return;
    setFileError(null);
    try {
      const { blob, filename } = await uploadsApi.download(slug, contribution.id);
      saveFile(blob, filename ?? contribution.original_filename ?? "dataset.csv");
      // The download was just written to the audit log, and that log is on this
      // page — so refresh it rather than let it show a stale history.
      uploadsApi.accessLog(slug).then(setAccessLog).catch(() => undefined);
    } catch (caught) {
      setFileError(caught instanceof Error ? caught.message : "Could not download the file.");
    }
  }

  useEffect(() => {
    if (!slug) return;
    projectsApi
      .get(slug)
      .then(setProject)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load."),
      );
    projectsApi.contributors(slug).then(setContributors).catch(() => setContributors([]));
    modelsApi.versions(slug).then(setVersions).catch(() => setVersions([]));
  }, [slug]);

  useEffect(() => {
    if (!slug || !user) return;
    loadPrivate(slug);
  }, [slug, user, loadPrivate]);

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

  const isOwner = project.viewer_role === "owner";
  const latest = versions[0] ?? null;
  const mainModels = latest?.models.filter((m) => m.track === "main") ?? [];
  const referenceModels = latest?.models.filter((m) => m.track === "reference") ?? [];
  const hasStake = isOwner || contributions.length > 0;
  const pending = contributions.filter((item) => item.status === "pending");

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
        {project.status === "archived" && <span className="badge warn">archived</span>}
        {project.viewer_role && <span className="badge">you: {project.viewer_role}</span>}
      </p>

      {project.description && <p className="lead">{project.description}</p>}

      <div className="cta-row">
        {user && project.status !== "archived" && (
          <Link to={`/projects/${project.slug}/upload`} className="primary button-like">
            {isOwner ? "Add measurements" : "Contribute my measurements"}
          </Link>
        )}
        {project.viewer_can_use_model && project.latest_version !== null && (
          <Link to={`/projects/${project.slug}/predict`} className="ghost button-like">
            Use the model
          </Link>
        )}
        {isOwner && (
          <Link to={`/projects/${project.slug}/settings`} className="ghost button-like">
            Settings
          </Link>
        )}
      </div>

      {user && !project.viewer_can_use_model && (
        <p className="muted small">
          The scores below are public. The model itself — its coefficients,
          prediction and export — unlocks when the owner accepts a contribution
          from you.
        </p>
      )}

      {/* Nobody is notified of a pending contribution, so it goes first. */}
      {isOwner && pending.length > 0 && (
        <>
          <h2>
            Awaiting your review ({pending.length})
          </h2>
          <p className="muted">
            Accepting adds the data to the model and gives the contributor access
            to it. That exchange is the reason anyone contributes, and reviewing
            is what stops it becoming a way to unlock a model by uploading noise.
          </p>
          {pending.map((item) => (
            <ReviewCard
              key={item.id}
              contribution={item}
              busy={busyId === item.id}
              onDownload={() => downloadFile(item)}
              onDecide={(decision, note) => decide(item, decision, note)}
              onCheckPoolability={() => checkPoolability(item)}
            />
          ))}
        </>
      )}

      <h2>Inputs and where the model applies</h2>
      <p className="muted">
        The declared range is a claim about the project. What licenses belief in
        a prediction is the range there is <em>data</em> for, and the lighter
        part of each bar is what other labs added to it.
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Quantity</th>
              <th scope="col">Unit</th>
              <th scope="col">Validity domain</th>
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
                <td className="domain-cell">
                  <DomainBar input={item} />
                </td>
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

      <div className="page-head">
        <h2>Model</h2>
        <div className="header-actions">
          {project.viewer_can_use_model && latest && (
            <button type="button" className="ghost" onClick={exportModel}>
              Export as JSON
            </button>
          )}
          {isOwner && (
            <button type="button" className="ghost" onClick={retrain}>
              Retrain
            </button>
          )}
        </div>
      </div>
      {training && <p className="muted small">{training}</p>}
      {fileError && (
        <p className="error" role="alert">
          {fileError}
        </p>
      )}

      {latest ? (
        <>
          <p className="muted">
            Version {latest.number}. Main engine{" "}
            <strong>{ENGINE_LABELS[project.main_engine]}</strong>, with a linear
            reference model trained alongside it so that contributors who
            improve the project without sharing their data still count.
          </p>
          <div className="model-grid">
            {mainModels.map((model) => (
              <ModelCard key={`main-${model.target_key}`} model={model} />
            ))}
          </div>
          {referenceModels.length > 0 && (
            <details className="details">
              <summary>
                Reference models ({referenceModels.length}) — the linear
                baseline everyone feeds
              </summary>
              <div className="model-grid">
                {referenceModels.map((model) => (
                  <ModelCard key={`ref-${model.target_key}`} model={model} />
                ))}
              </div>
            </details>
          )}
          {project.viewer_can_use_model && (
            <p className="muted small">
              The export is a self-contained JSON document — units, metrics and
              the exact contributions behind the fit — so a reader of a paper
              can tell what these numbers were fitted on.
            </p>
          )}
        </>
      ) : (
        <div className="notice">
          <p>
            No model yet. A model is fitted as soon as the project holds
            accepted measurements.
          </p>
        </div>
      )}

      <h2>Versions</h2>
      <VersionTimeline versions={versions} />

      <h2>Contributors</h2>
      <ContributorList contributors={contributors} />

      {user && (
        <>
          <h2>{isOwner ? "All contributions" : "My contributions"}</h2>
          {contributions.length === 0 ? (
            <p className="muted">
              {isOwner
                ? "No data yet. Add your own measurements to give the project something to build on."
                : "You have not contributed to this project yet."}
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Contributor</th>
                    <th scope="col">Rows</th>
                    <th scope="col">Method</th>
                    <th scope="col">File</th>
                    <th scope="col">Status</th>
                    <th scope="col">Decision</th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {contributions.map((item) => (
                    <tr key={item.id}>
                      <td>{item.contributor_name}</td>
                      <td>{item.n_rows}</td>
                      <td>{item.measurement_method ?? "—"}</td>
                      <td className="small">
                        {item.original_filename ? (
                          <button
                            type="button"
                            className="ghost tiny-button"
                            onClick={() => downloadFile(item)}
                          >
                            {item.original_filename}
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <span
                          className={`badge${
                            item.status === "pending"
                              ? " warn"
                              : item.status === "accepted"
                                ? ""
                                : " muted-badge"
                          }`}
                        >
                          {item.status}
                        </span>
                      </td>
                      <td className="small">{item.review_note ?? "—"}</td>
                      <td className="row-actions">
                        {/* The owner rejects; the contributor withdraws. They
                            are different acts and are recorded differently. */}
                        {isOwner && item.status === "accepted" && (
                          <button
                            type="button"
                            className="ghost tiny-button"
                            disabled={busyId === item.id}
                            onClick={() => decide(item, "reject", "")}
                          >
                            Remove from model
                          </button>
                        )}
                        {/* Converting rather than uploading again: the same row
                            changes mode, so the data cannot be counted twice
                            (ARCHITECTURE.md §5.5). */}
                        {!isOwner && item.mode === "federated" && item.status !== "withdrawn" && (
                          <Link
                            to={`/projects/${project.slug}/upload?share=${item.id}`}
                            className="ghost button-like tiny-button"
                          >
                            Share the file
                          </Link>
                        )}
                        {!isOwner &&
                          (item.status === "pending" || item.status === "accepted") && (
                            <button
                              type="button"
                              className="ghost tiny-button"
                              disabled={busyId === item.id}
                              onClick={() => withdraw(item)}
                            >
                              Withdraw
                            </button>
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!isOwner && contributions.some((item) => item.status === "accepted") && (
            <p className="muted small">
              Withdrawing takes your data out of the model and your access to the
              model with it. Access is the counterpart of the data being there,
              not a reward for having once uploaded it.
            </p>
          )}
          {contributions.some((item) => item.original_filename) && (
            <p className="muted small">
              Downloading a file records who opened it and when, below. That
              applies to the owner as much as to anyone else.
            </p>
          )}
        </>
      )}

      {user && hasStake && (
        <>
          <h2>Who has read these files</h2>
          <AccessLog entries={accessLog} isOwner={isOwner} />
        </>
      )}
    </section>
  );
}
