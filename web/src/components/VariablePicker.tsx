/* Pick quantities from the shared registry, and add one when it is missing.
 *
 * The registry is what makes discovery by input variable work at all — under
 * free-text naming, forty projects spell "cutting speed" forty ways and none
 * of them find each other. But a registry with no escape hatch turns its own
 * incompleteness into the reason the first researcher with an unusual
 * measurement walks away, so proposing a new quantity is inline, immediate,
 * and does not block on moderation.
 */

import { useEffect, useState } from "react";

import { variables as variablesApi, type Variable } from "../lib/api";

interface Props {
  /** Variable keys already chosen here. */
  selected: string[];
  /** Keys chosen elsewhere on the form — offered but flagged, since a variable
   *  cannot be both an input and a target of the same project. */
  unavailable?: string[];
  onAdd: (variable: Variable) => void;
  label: string;
}

export default function VariablePicker({ selected, unavailable = [], onAdd, label }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Variable[]>([]);
  const [proposing, setProposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      variablesApi
        .list({ q: query || undefined })
        .then((data) => {
          if (!cancelled) setResults(data);
        })
        .catch(() => {
          if (!cancelled) setResults([]);
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  return (
    <div className="picker">
      <div className="field-row">
        <label htmlFor={`picker-${label}`}>{label}</label>
        <input
          id={`picker-${label}`}
          value={query}
          placeholder="search the registry: speed, angle, stress…"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <ul className="picker-results">
        {results.map((variable) => {
          const taken = selected.includes(variable.key);
          const clash = unavailable.includes(variable.key);
          return (
            <li key={variable.id}>
              <button
                type="button"
                className="ghost picker-item"
                disabled={taken || clash}
                onClick={() => onAdd(variable)}
              >
                <span>
                  <strong>{variable.display_name}</strong>
                  {variable.symbol && <span className="muted"> {variable.symbol}</span>}
                  {variable.unit && <span className="muted"> · {variable.unit}</span>}
                </span>
                <span className="small muted">
                  {taken ? "added" : clash ? "used as a target" : "add"}
                </span>
              </button>
            </li>
          );
        })}
        {results.length === 0 && query && (
          <li className="muted small">Nothing in the registry matches “{query}”.</li>
        )}
      </ul>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!proposing ? (
        <button type="button" className="ghost" onClick={() => setProposing(true)}>
          My quantity is not listed
        </button>
      ) : (
        <ProposeVariable
          initialName={query}
          onCancel={() => setProposing(false)}
          onCreated={(variable) => {
            setProposing(false);
            setError(null);
            onAdd(variable);
          }}
          onError={setError}
        />
      )}
    </div>
  );
}

function slugKey(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
}

function ProposeVariable({
  initialName,
  onCancel,
  onCreated,
  onError,
}: {
  initialName: string;
  onCancel: () => void;
  onCreated: (variable: Variable) => void;
  onError: (message: string | null) => void;
}) {
  const [name, setName] = useState(initialName);
  const [unit, setUnit] = useState("");
  const [symbol, setSymbol] = useState("");
  const [dimension, setDimension] = useState("");
  const [busy, setBusy] = useState(false);

  // The key must start with a letter and hold only [a-z0-9_], matching the
  // server's pattern. Derived rather than asked for: it is an implementation
  // detail nobody should have to think about.
  const key = slugKey(name) || "";
  const keyValid = /^[a-z][a-z0-9_]*$/.test(key) && key.length >= 2;

  async function submit() {
    setBusy(true);
    onError(null);
    try {
      const variable = await variablesApi.propose({
        key,
        display_name: name.trim(),
        symbol: symbol || undefined,
        unit: unit || undefined,
        dimension: dimension || undefined,
        aliases: [name.trim()],
      });
      onCreated(variable);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Could not add the quantity.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="propose-box">
      <h4>Add a quantity</h4>
      <p className="muted small">
        Usable in your project straight away. It is also queued for review, and
        joins the shared registry if accepted — which is what lets other people
        find your project by this variable later.
      </p>

      <div className="propose-grid">
        <div className="field-row">
          <label htmlFor="p-name">Name</label>
          <input
            id="p-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Tool nose radius"
          />
        </div>
        <div className="field-row">
          <label htmlFor="p-unit">Unit</label>
          <input
            id="p-unit"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="mm"
          />
        </div>
        <div className="field-row">
          <label htmlFor="p-symbol">
            Symbol <span className="hint">optional</span>
          </label>
          <input id="p-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </div>
        <div className="field-row">
          <label htmlFor="p-dimension">
            Dimension <span className="hint">optional — length, speed, angle…</span>
          </label>
          <input
            id="p-dimension"
            value={dimension}
            onChange={(e) => setDimension(e.target.value)}
          />
        </div>
      </div>

      {name && !keyValid && (
        <p className="muted small">
          That name does not produce a usable identifier — it needs at least two
          latin letters.
        </p>
      )}
      {keyValid && (
        <p className="muted small">
          Identifier: <code>{key}</code>
        </p>
      )}

      <div className="cta-row">
        <button
          type="button"
          className="primary"
          disabled={busy || !name.trim() || !keyValid}
          onClick={submit}
        >
          {busy ? "Adding…" : "Add and use it"}
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
