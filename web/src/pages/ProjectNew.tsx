/* Declaring a project: what you measure, and what you predict.
 *
 * One page with numbered sections rather than a multi-step wizard that hides
 * later steps. The choices interact — a variable used as a target cannot also
 * be an input, and the engine determines whether federated contributions can
 * ever be used — and someone deciding whether the platform fits their work
 * should be able to see the whole shape of the declaration at once.
 */

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import VariablePicker from "../components/VariablePicker";
import {
  ENGINE_LABELS,
  FEDERATED_COMPATIBLE,
  projects as projectsApi,
  type Engine,
  type Variable,
} from "../lib/api";

interface ChosenInput {
  variable: Variable;
  unit: string;
  expectedMin: string;
  expectedMax: string;
  penalisedSign: string; // "", "-1" or "1" — a select, so it is text here
}

export default function ProjectNew() {
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [material, setMaterial] = useState("");
  const [process, setProcess] = useState("");
  const [visibility, setVisibility] = useState<"public" | "unlisted">("public");
  const [engine, setEngine] = useState<Engine>("piml");
  const [licence, setLicence] = useState("CC-BY-4.0");

  const [inputs, setInputs] = useState<ChosenInput[]>([]);
  const [targets, setTargets] = useState<Variable[]>([]);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inputKeys = inputs.map((item) => item.variable.key);
  const targetKeys = targets.map((variable) => variable.key);
  const canSubmit = title.trim().length >= 3 && inputs.length > 0 && targets.length > 0;

  function addInput(variable: Variable) {
    setInputs((current) => [
      ...current,
      {
        variable,
        unit: variable.unit ?? "",
        expectedMin: "",
        expectedMax: "",
        penalisedSign:
          variable.penalised_sign === null ? "" : String(variable.penalised_sign),
      },
    ]);
  }

  function updateInput(index: number, patch: Partial<ChosenInput>) {
    setInputs((current) =>
      current.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }

  function move(index: number, delta: number) {
    setInputs((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      const a = next[index];
      const b = next[target];
      if (!a || !b) return current;
      next[index] = b;
      next[target] = a;
      return next;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const project = await projectsApi.create({
        title: title.trim(),
        description: description || undefined,
        material: material || undefined,
        process: process || undefined,
        visibility,
        main_engine: engine,
        accepts_federated: true,
        licence: licence || undefined,
        inputs: inputs.map((item) => ({
          variable_key: item.variable.key,
          required: true,
          unit: item.unit || null,
          expected_min: item.expectedMin === "" ? null : Number(item.expectedMin),
          expected_max: item.expectedMax === "" ? null : Number(item.expectedMax),
          penalised_sign: item.penalisedSign === "" ? null : Number(item.penalisedSign),
        })),
        targets: targets.map((variable) => ({
          variable_key: variable.key,
          unit: variable.unit,
        })),
      });
      navigate(`/projects/${project.slug}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the project.");
    } finally {
      setBusy(false);
    }
  }

  const engineTakesFederated = FEDERATED_COMPATIBLE.includes(engine);

  return (
    <section>
      <h1>Create a project</h1>
      <p className="lead">
        A project is a declaration: these are the quantities I measure, this is
        what I predict. Everything else follows from it — which files can be
        matched to your project, and who can contribute to it.
      </p>

      <form onSubmit={submit} noValidate>
        {/* 1 ------------------------------------------------------------- */}
        <h2>
          <span className="num">1</span> What it is
        </h2>
        <div className="field-row">
          <label htmlFor="title">Title</label>
          <input
            id="title"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Residual stress in orthogonal turning of Ti-6Al-4V"
          />
        </div>
        <div className="field-row wide">
          <label htmlFor="description">
            Description <span className="hint">what a visitor needs to judge whether their data fits</span>
          </label>
          <textarea
            id="description"
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="field-row">
          <label htmlFor="material">
            Material <span className="hint">optional</span>
          </label>
          <input
            id="material"
            value={material}
            onChange={(e) => setMaterial(e.target.value)}
            placeholder="Ti-6Al-4V"
          />
        </div>
        <div className="field-row">
          <label htmlFor="process">
            Process <span className="hint">optional</span>
          </label>
          <input
            id="process"
            value={process}
            onChange={(e) => setProcess(e.target.value)}
            placeholder="orthogonal turning"
          />
        </div>

        {/* 2 ------------------------------------------------------------- */}
        <h2>
          <span className="num">2</span> Inputs
        </h2>
        <p className="muted">
          The quantities you vary and record. Their order is part of the
          project's contract — a contributor's columns are matched to it — so it
          is stored as you arrange it here.
        </p>

        {inputs.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Quantity</th>
                  <th scope="col">Unit</th>
                  <th scope="col">Expected range</th>
                  <th scope="col">Physical prior</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {inputs.map((item, index) => (
                  <tr key={item.variable.key}>
                    <td className="muted">{index + 1}</td>
                    <td>
                      <strong>{item.variable.display_name}</strong>
                      {item.variable.symbol && (
                        <span className="muted"> {item.variable.symbol}</span>
                      )}
                      <br />
                      <code className="small">{item.variable.key}</code>
                    </td>
                    <td>
                      <input
                        aria-label={`Unit for ${item.variable.display_name}`}
                        className="tiny"
                        value={item.unit}
                        onChange={(e) => updateInput(index, { unit: e.target.value })}
                      />
                    </td>
                    <td className="range-cell">
                      <input
                        aria-label={`Minimum for ${item.variable.display_name}`}
                        className="tiny"
                        inputMode="decimal"
                        placeholder="min"
                        value={item.expectedMin}
                        onChange={(e) => updateInput(index, { expectedMin: e.target.value })}
                      />
                      <input
                        aria-label={`Maximum for ${item.variable.display_name}`}
                        className="tiny"
                        inputMode="decimal"
                        placeholder="max"
                        value={item.expectedMax}
                        onChange={(e) => updateInput(index, { expectedMax: e.target.value })}
                      />
                    </td>
                    <td>
                      {/* Used by the PIML engine: it penalises a fit whose
                          coefficient takes the sign physics forbids. Soft, not
                          a hard constraint. */}
                      <select
                        aria-label={`Physical prior for ${item.variable.display_name}`}
                        value={item.penalisedSign}
                        onChange={(e) =>
                          updateInput(index, { penalisedSign: e.target.value })
                        }
                      >
                        <option value="">no prior</option>
                        <option value="-1">should not decrease the target</option>
                        <option value="1">should not increase the target</option>
                      </select>
                    </td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="ghost tiny-button"
                        onClick={() => move(index, -1)}
                        disabled={index === 0}
                        aria-label={`Move ${item.variable.display_name} up`}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="ghost tiny-button"
                        onClick={() => move(index, 1)}
                        disabled={index === inputs.length - 1}
                        aria-label={`Move ${item.variable.display_name} down`}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className="ghost tiny-button"
                        onClick={() =>
                          setInputs((current) => current.filter((_, i) => i !== index))
                        }
                        aria-label={`Remove ${item.variable.display_name}`}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <VariablePicker
          label="Add an input"
          selected={inputKeys}
          unavailable={targetKeys}
          onAdd={addInput}
        />

        {/* 3 ------------------------------------------------------------- */}
        <h2>
          <span className="num">3</span> Targets
        </h2>
        <p className="muted">
          What the model predicts. A project may have several — the original
          residual-stress work predicts both the axial and the circumferential
          component from the same inputs.
        </p>

        {targets.length > 0 && (
          <ul className="chip-list">
            {targets.map((variable) => (
              <li key={variable.key} className="chip">
                <span>
                  {variable.display_name}
                  {variable.unit && <span className="muted"> · {variable.unit}</span>}
                </span>
                <button
                  type="button"
                  className="ghost tiny-button"
                  onClick={() =>
                    setTargets((current) => current.filter((v) => v.key !== variable.key))
                  }
                  aria-label={`Remove ${variable.display_name}`}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}

        <VariablePicker
          label="Add a target"
          selected={targetKeys}
          unavailable={inputKeys}
          onAdd={(variable) => setTargets((current) => [...current, variable])}
        />

        {/* 4 ------------------------------------------------------------- */}
        <h2>
          <span className="num">4</span> Model and policy
        </h2>
        <div className="field-row">
          <label htmlFor="engine">Main engine</label>
          <select
            id="engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value as Engine)}
          >
            {(Object.keys(ENGINE_LABELS) as Engine[]).map((key) => (
              <option key={key} value={key}>
                {ENGINE_LABELS[key]}
              </option>
            ))}
          </select>
        </div>

        <div className="notice">
          <p>
            Your project always trains <strong>two</strong> models. A{" "}
            <strong>reference</strong> model in the linear family, fed by every
            contributor including those who do not share their data; and the{" "}
            <strong>main</strong> model above, fed only by contributors who
            share their files.
          </p>
          <p className="muted small">
            {engineTakesFederated
              ? "This engine can also be fitted from summary sums alone, so it could absorb non-sharing contributions directly."
              : "This engine needs the individual rows, so it cannot be fitted from summary sums — which is exactly why the reference model exists. Nobody's contribution goes to waste."}
          </p>
        </div>

        <div className="field-row">
          <label htmlFor="licence">
            Licence for the project <span className="hint">contributors choose their own per dataset</span>
          </label>
          <input id="licence" value={licence} onChange={(e) => setLicence(e.target.value)} />
        </div>

        <div className="field-row">
          <label htmlFor="visibility">Visibility</label>
          <select
            id="visibility"
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as "public" | "unlisted")}
          >
            <option value="public">Public — listed in discovery</option>
            <option value="unlisted">Unlisted — reachable by link only</option>
          </select>
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <div className="cta-row">
          <button className="primary" type="submit" disabled={busy || !canSubmit}>
            {busy ? "Creating…" : "Create project"}
          </button>
          {!canSubmit && (
            <span className="muted small">
              A title, at least one input and at least one target are needed.
            </span>
          )}
        </div>
      </form>
    </section>
  );
}
