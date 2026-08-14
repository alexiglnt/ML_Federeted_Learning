/* Project settings, for the owner.
 *
 * What is editable here is everything that does not change the meaning of the
 * data already recorded. Inputs and targets are therefore absent, and their
 * absence is explained on the page rather than merely enforced: adding or
 * removing an input would invalidate every column mapping already stored
 * against this project, silently, and no owner can re-map their contributors'
 * files on their behalf. A different set of inputs is a different project.
 *
 * Bounds and physical priors *can* move, because they are claims about the
 * project rather than facts about the stored rows. Priors only take effect at
 * the next training run, which the page says out loud — a prior edited with no
 * retrain looks applied and is not.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  ENGINE_LABELS,
  FEDERATED_COMPATIBLE,
  projects as projectsApi,
  type Engine,
  type ProjectDetail,
  type ProjectUpdatePayload,
} from "../lib/api";

type Bounds = { min: string; max: string; sign: string };

function boundsFrom(detail: ProjectDetail): Record<string, Bounds> {
  const out: Record<string, Bounds> = {};
  for (const item of detail.inputs) {
    out[item.variable.key] = {
      min: item.expected_min === null ? "" : String(item.expected_min),
      max: item.expected_max === null ? "" : String(item.expected_max),
      sign: item.penalised_sign === null ? "" : String(item.penalised_sign),
    };
  }
  return out;
}

/** Blank clears the bound; the endpoint distinguishes "absent" from "null". */
function toNumber(raw: string): number | null | undefined {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

export default function ProjectSettings() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [form, setForm] = useState<ProjectUpdatePayload>({});
  const [bounds, setBounds] = useState<Record<string, Bounds>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmTitle, setConfirmTitle] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function adopt(detail: ProjectDetail) {
    setProject(detail);
    setForm({
      title: detail.title,
      description: detail.description ?? "",
      material: detail.material ?? "",
      process: detail.process ?? "",
      visibility: detail.visibility,
      main_engine: detail.main_engine,
      accepts_federated: detail.accepts_federated,
      licence: detail.licence ?? "",
      status: detail.status,
    });
    setBounds(boundsFrom(detail));
  }

  useEffect(() => {
    if (!slug) return;
    projectsApi
      .get(slug)
      .then(adopt)
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not load the project."),
      );
  }, [slug]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!slug || !project) return;

    const input_bounds: NonNullable<ProjectUpdatePayload["input_bounds"]> = {};
    for (const [key, entry] of Object.entries(bounds)) {
      const min = toNumber(entry.min);
      const max = toNumber(entry.max);
      if (min === undefined || max === undefined) {
        setError(`The declared range for ${key} must be numeric or empty.`);
        return;
      }
      if (min !== null && max !== null && min > max) {
        setError(`The declared range for ${key} runs backwards.`);
        return;
      }
      input_bounds[key] = {
        expected_min: min,
        expected_max: max,
        penalised_sign: entry.sign === "" ? null : Number(entry.sign),
      };
    }

    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      adopt(await projectsApi.update(slug, { ...form, input_bounds }));
      setSaved("Saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteProject() {
    if (!slug) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await projectsApi.remove(slug);
      navigate("/projects");
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : "Could not delete the project.");
      setDeleting(false);
    }
  }

  if (error && !project) {
    return (
      <section>
        <h1>Settings</h1>
        <p className="error" role="alert">
          {error}
        </p>
      </section>
    );
  }
  if (!project) return <p className="muted">Loading…</p>;

  if (project.viewer_role !== "owner") {
    return (
      <section>
        <p className="eyebrow">
          <Link to={`/projects/${project.slug}`}>{project.title}</Link>
        </p>
        <h1>Settings</h1>
        <p className="muted">Only the owner of a project can change its settings.</p>
      </section>
    );
  }

  const engineChanged = form.main_engine !== project.main_engine;

  return (
    <section>
      <p className="eyebrow">
        <Link to={`/projects/${project.slug}`}>{project.title}</Link>
      </p>
      <h1>Project settings</h1>

      <form onSubmit={save}>
        <h2>Description</h2>
        <div className="field-row wide">
          <label htmlFor="title">Title</label>
          <input
            id="title"
            value={form.title ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            required
            minLength={3}
          />
          <span className="hint">
            The address of this project never changes, whatever the title says —
            a link handed to a colleague or printed in a paper keeps working.
          </span>
        </div>
        <div className="field-row wide">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            rows={4}
            value={form.description ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
        </div>
        <div className="predict-grid">
          <div className="field-row">
            <label htmlFor="material">Material</label>
            <input
              id="material"
              value={form.material ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, material: e.target.value }))}
            />
          </div>
          <div className="field-row">
            <label htmlFor="process">Process</label>
            <input
              id="process"
              value={form.process ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, process: e.target.value }))}
            />
          </div>
          <div className="field-row">
            <label htmlFor="licence">Licence</label>
            <input
              id="licence"
              value={form.licence ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, licence: e.target.value }))}
              placeholder="CC-BY-4.0"
            />
            <span className="hint">
              Carried into the model export, so a reader knows the terms.
            </span>
          </div>
        </div>

        <h2>Model</h2>
        <div className="predict-grid">
          <div className="field-row">
            <label htmlFor="engine">Main engine</label>
            <select
              id="engine"
              value={form.main_engine ?? project.main_engine}
              onChange={(e) =>
                setForm((f) => ({ ...f, main_engine: e.target.value as Engine }))
              }
            >
              {(Object.keys(ENGINE_LABELS) as Engine[]).map((engine) => (
                <option key={engine} value={engine}>
                  {ENGINE_LABELS[engine]}
                </option>
              ))}
            </select>
            <span className="hint">
              {FEDERATED_COMPATIBLE.includes(form.main_engine ?? project.main_engine)
                ? "Fits from summed statistics, so it can absorb a contribution made without sharing a file."
                : "Needs the individual rows, so only shared files feed it. The linear reference model still takes everyone's."}
            </span>
          </div>
          <div className="field-row">
            <label htmlFor="federated">Contributions without sharing a file</label>
            <select
              id="federated"
              value={form.accepts_federated ? "yes" : "no"}
              onChange={(e) =>
                setForm((f) => ({ ...f, accepts_federated: e.target.value === "yes" }))
              }
            >
              <option value="yes">Accepted</option>
              <option value="no">Not accepted</option>
            </select>
            <span className="hint">
              They feed the reference model and widen the published domain, and
              they never unlock model access.
            </span>
          </div>
        </div>
        {engineChanged && (
          <p className="muted small">
            The engine changes what the next training run fits. The published
            model stays as it is until you retrain from the project page.
          </p>
        )}

        <h2>Visibility</h2>
        <div className="predict-grid">
          <div className="field-row">
            <label htmlFor="visibility">Listing</label>
            <select
              id="visibility"
              value={form.visibility ?? project.visibility}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  visibility: e.target.value as ProjectDetail["visibility"],
                }))
              }
            >
              <option value="public">Public — listed and searchable</option>
              <option value="unlisted">Unlisted — reachable only by its link</option>
            </select>
            <span className="hint">
              Neither setting hides the model or the files; both are governed by
              contribution, not by this.
            </span>
          </div>
          <div className="field-row">
            <label htmlFor="status">Status</label>
            <select
              id="status"
              value={form.status ?? project.status}
              onChange={(e) =>
                setForm((f) => ({ ...f, status: e.target.value as ProjectDetail["status"] }))
              }
            >
              <option value="draft">Draft</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
            <span className="hint">
              An archived project stops taking uploads. Everything already
              published on it stays readable.
            </span>
          </div>
        </div>

        <h2>Declared range and physical priors</h2>
        <p className="muted">
          The declared range is what the project claims to be about. It is never
          a filter: data outside it is accepted and warned about, because
          measurements from a regime nobody has covered are the most valuable
          contribution there is.
        </p>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Quantity</th>
                <th scope="col">Declared min</th>
                <th scope="col">Declared max</th>
                <th scope="col">Physical prior</th>
                <th scope="col">Covered by data</th>
              </tr>
            </thead>
            <tbody>
              {project.inputs.map((item) => {
                const key = item.variable.key;
                const entry = bounds[key] ?? { min: "", max: "", sign: "" };
                const set = (patch: Partial<Bounds>) =>
                  setBounds((current) => ({ ...current, [key]: { ...entry, ...patch } }));
                return (
                  <tr key={key}>
                    <td>
                      <strong>{item.variable.display_name}</strong>
                      <br />
                      <span className="muted small">{item.unit ?? "—"}</span>
                    </td>
                    <td>
                      <input
                        className="tiny"
                        type="number"
                        step="any"
                        aria-label={`Declared minimum for ${item.variable.display_name}`}
                        value={entry.min}
                        onChange={(e) => set({ min: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="tiny"
                        type="number"
                        step="any"
                        aria-label={`Declared maximum for ${item.variable.display_name}`}
                        value={entry.max}
                        onChange={(e) => set({ max: e.target.value })}
                      />
                    </td>
                    <td>
                      <select
                        aria-label={`Physical prior for ${item.variable.display_name}`}
                        value={entry.sign}
                        onChange={(e) => set({ sign: e.target.value })}
                      >
                        <option value="">no prior</option>
                        <option value="1">should not increase the target</option>
                        <option value="-1">should not decrease the target</option>
                      </select>
                    </td>
                    <td className="small muted">
                      {item.observed_min === null || item.observed_max === null
                        ? "no data yet"
                        : `${item.observed_min} → ${item.observed_max}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          A prior applies to every target of this project. That holds while the
          targets respond alike to an input; a project predicting two quantities
          that respond oppositely needs one prior per target, which is not built
          (see ROADMAP.md). Priors take effect at the next training run.
        </p>

        <div className="notice">
          <p>
            <strong>Inputs and targets cannot be changed.</strong> Every file
            contributed here was mapped column by column against the current
            list, and altering it would leave those mappings quietly wrong. A
            different set of quantities is a different project.
          </p>
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {saved && <p className="muted" role="status">{saved}</p>}

        <div className="cta-row">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save settings"}
          </button>
          <Link to={`/projects/${project.slug}`} className="ghost button-like">
            Back to the project
          </Link>
        </div>
      </form>

      <div className="notice danger-zone">
        <h2>Danger zone</h2>
        <p>
          Deletes this project and everything recorded against it —
          contributions, model versions, access grants. Contributed files are
          not removed from storage, the same as a rejected contribution's file
          stays. This cannot be undone.
        </p>

        {!confirmingDelete ? (
          <button type="button" className="danger" onClick={() => setConfirmingDelete(true)}>
            Delete this project
          </button>
        ) : (
          <div className="field-row wide">
            <label htmlFor="confirm-delete">
              Type <strong>{project.title}</strong> to confirm
            </label>
            <input
              id="confirm-delete"
              value={confirmTitle}
              onChange={(e) => setConfirmTitle(e.target.value)}
              autoComplete="off"
            />
            {deleteError && (
              <p className="error" role="alert">
                {deleteError}
              </p>
            )}
            <div className="cta-row">
              <button
                type="button"
                className="danger"
                disabled={confirmTitle !== project.title || deleting}
                onClick={deleteProject}
              >
                {deleting ? "Deleting…" : "Delete permanently"}
              </button>
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  setConfirmingDelete(false);
                  setConfirmTitle("");
                  setDeleteError(null);
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
