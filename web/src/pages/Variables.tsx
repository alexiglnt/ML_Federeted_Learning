import { useEffect, useState } from "react";

import { variables as variablesApi, type Variable } from "../lib/api";

/** The registry, browsable. Public on purpose: it is the shared vocabulary the
 *  whole platform is built on, and someone deciding whether their measurements
 *  fit here should be able to check without creating an account first. */
export default function Variables() {
  const [rows, setRows] = useState<Variable[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // Debounced so typing does not fire a request per keystroke.
    const timer = setTimeout(() => {
      variablesApi
        .list({ q: query || undefined })
        .then((data) => {
          if (!cancelled) setRows(data);
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setError(caught instanceof Error ? caught.message : "Could not load.");
          }
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
      <h1>Variable registry</h1>
      <p className="lead">
        Projects pick their inputs from this shared list rather than naming them
        freely. That is what makes it possible to search for a project by the
        variables it uses, to convert between units automatically, and to match
        the columns of an uploaded file reliably.
      </p>
      <p className="muted">
        Missing a quantity? You can add it while creating a project — it becomes
        usable immediately and is reviewed for inclusion here in parallel.
      </p>

      <div className="field-row">
        <label htmlFor="q">Search</label>
        <input
          id="q"
          value={query}
          placeholder="speed, angle, stress…"
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
          Nothing matches. If the database was just created, the registry may not
          be seeded yet.
        </p>
      )}

      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Quantity</th>
                <th scope="col">Symbol</th>
                <th scope="col">Unit</th>
                <th scope="col">Dimension</th>
                <th scope="col">Physical prior</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((variable) => (
                <tr key={variable.id}>
                  <td>
                    <strong>{variable.display_name}</strong>
                    <br />
                    <code className="muted small">{variable.key}</code>
                    {variable.description && (
                      <p className="muted small">{variable.description}</p>
                    )}
                  </td>
                  <td>{variable.symbol ?? "—"}</td>
                  <td>{variable.unit ?? "—"}</td>
                  <td>{variable.dimension ?? "—"}</td>
                  <td className="small">
                    {/* The sign a coefficient is *forbidden* to take, used by
                        the PIML engine to penalise fits that contradict known
                        physics. */}
                    {variable.penalised_sign === null
                      ? "—"
                      : variable.penalised_sign < 0
                        ? "coefficient must not be negative"
                        : "coefficient must not be positive"}
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
