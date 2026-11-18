/* Every engine scored on the same rows, and the one the site would suggest.
 *
 * A suggestion, never a switch: on the dozen rows typical here, small gaps
 * between engines are noise, and the choice of main engine also weighs things
 * a score does not see — a readable equation, absorbing federated
 * contributions. So the owner reads the table and decides.
 *
 * The comparison is re-run on every version. The first file's verdict is
 * provisional by nature (one lab cannot measure how a model travels), and the
 * table is how the owner finds out when another engine has overtaken theirs.
 */

import InfoTip from "./InfoTip";
import { ENGINE_LABELS, type Engine, type EngineBenchmark as Benchmark } from "../lib/api";

function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(3);
}

/** Below this, the ranking is shown but flagged as provisional. */
const FEW_ROWS = 15;

interface Props {
  benchmark: Benchmark;
  currentEngine: Engine;
  targetNames: Record<string, string>;
  canChoose: boolean;
  busy: boolean;
  onChoose: (engine: Engine) => void;
}

export default function EngineBenchmark({
  benchmark,
  currentEngine,
  targetNames,
  canChoose,
  busy,
  onChoose,
}: Props) {
  const { suggestion } = benchmark;
  const suggested = suggestion.suggested;
  const basisLabel =
    suggestion.basis === "r2_leave_one_lab_out" ? "R² across labs" : "cross-validated R²";

  const allRows = Object.values(benchmark.targets).flat();
  const nRows = Math.min(...allRows.map((r) => r.n_train));
  const nSources = Math.max(...allRows.map((r) => r.n_sources));
  const provisional = nRows < FEW_ROWS || nSources < 2;

  return (
    <div className="benchmark">
      {suggested && (
        <div className="notice">
          <p>
            Suggested main engine: <strong>{ENGINE_LABELS[suggested]}</strong>
            {suggested === currentEngine ? " — the one this project already uses." : "."}{" "}
            <span className="muted small">
              Best average {basisLabel}; engines within {suggestion.margin} of the best
              are treated as tied, and the simplest of them is suggested.
            </span>
          </p>
          {provisional && (
            <p className="muted small">
              Provisional:{" "}
              {nSources < 2
                ? "all the data comes from one contributor, so nothing yet says how each engine does on another lab's measurements."
                : `only ${nRows} rows, so small differences between engines are mostly noise.`}
            </p>
          )}
          {canChoose && suggested !== currentEngine && (
            <p>
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() => onChoose(suggested)}
              >
                Use {ENGINE_LABELS[suggested]} and retrain
              </button>
            </p>
          )}
        </div>
      )}

      {Object.entries(benchmark.targets).map(([key, rows]) => (
        <div key={key} className="table-scroll">
          <table className="data-table">
            <caption className="small">{targetNames[key] ?? key}</caption>
            <thead>
              <tr>
                <th scope="col">Engine</th>
                <th scope="col">
                  R² across labs
                  <InfoTip
                    label="R² across labs"
                    text="Leave-one-lab-out: trained on every contributor but one, scored on the one left out. Needs at least two contributors."
                  />
                </th>
                <th scope="col">
                  Cross-validated R²
                  <InfoTip
                    label="Cross-validated R²"
                    text="Scored on rows held out of the fit. Hyperparameters (PIML's lambda, ridge's alpha) are chosen inside each fold so no engine is flattered."
                  />
                </th>
                <th scope="col">RMSE (CV)</th>
                <th scope="col">Properties</th>
                {canChoose && <th scope="col" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.engine} className={row.engine === suggested ? "suggested-row" : undefined}>
                  <td>
                    {ENGINE_LABELS[row.engine]}{" "}
                    {row.engine === currentEngine && <span className="badge">current</span>}{" "}
                    {row.engine === suggested && <span className="badge good">suggested</span>}
                  </td>
                  <td>{score(row.r2_leave_one_lab_out)}</td>
                  <td>{score(row.r2_cv)}</td>
                  <td>{score(row.rmse_cv)}</td>
                  <td className="small">
                    {row.error ? (
                      <span className="badge danger" title={row.error}>
                        failed
                      </span>
                    ) : (
                      <span className="badge-row">
                        {row.has_equation && <span className="badge">equation</span>}
                        {row.federated_compatible && <span className="badge">federated</span>}
                      </span>
                    )}
                  </td>
                  {canChoose && (
                    <td className="row-actions">
                      {row.engine !== currentEngine && !row.error && (
                        <button
                          type="button"
                          className="ghost tiny-button"
                          disabled={busy}
                          onClick={() => onChoose(row.engine)}
                        >
                          Use this
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
