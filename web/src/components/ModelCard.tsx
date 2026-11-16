/* One fitted model, with its scores read in the right order.
 *
 * Training R² is shown last and quietly. Five parameters fitted on seven
 * points look excellent whatever the data says, and leading with that number
 * would mislead every reader — which is why the original site refused to show
 * it on its own. What is worth reading is the out-of-sample score, and above
 * all leave-one-lab-out: it is the only one that answers "does this model work
 * anywhere other than where it was built", and no single lab can compute it.
 */

import InfoTip from "./InfoTip";
import { ENGINE_LABELS, type FittedModelOut } from "../lib/api";

function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(3);
}

export default function ModelCard({ model }: { model: FittedModelOut }) {
  const m = model.metrics;
  const lolo = m.r2_leave_one_lab_out;

  return (
    <article className="model-card">
      <header>
        <h3>
          {model.target_name}
          {model.target_unit && <span className="muted"> ({model.target_unit})</span>}
        </h3>
        <p className="meta-line small">
          <span>{ENGINE_LABELS[model.engine]}</span>
          <span>{model.n_train} rows</span>
          {model.track === "reference" && (
            <span className="badge">reference</span>
          )}
        </p>
      </header>

      <dl className="score-grid">
        <div className={lolo === null || lolo === undefined ? "score muted-score" : "score headline"}>
          <dt>
            R² across labs
            <InfoTip
              label="R² across labs"
              text="Leave-one-lab-out: the model is trained on every contributor but one, then scored on the one left out. The only score that answers whether this works anywhere beyond where it was built."
            />
          </dt>
          <dd>{score(lolo)}</dd>
          <p className="hint">
            {lolo === null || lolo === undefined
              ? `Needs data from at least two contributors — this has ${m.n_sources ?? 0}.`
              : "Trained on all labs but one, tested on the one left out. The question a reader actually has."}
          </p>
        </div>
        <div className="score">
          <dt>
            R² out of sample
            <InfoTip
              label="R² out of sample"
              text="Fraction of the target's variation the model explains on data it wasn't fitted on. 1 is a perfect fit, 0 is no better than always guessing the average, negative is worse than that."
            />
          </dt>
          <dd>{score(m.r2_cv)}</dd>
          <p className="hint">{m.cv_scheme ?? "cross-validated"}</p>
        </div>
        <div className="score">
          <dt>
            RMSE out of sample
            <InfoTip
              label="RMSE out of sample"
              text="Typical prediction error, in the target's own units — lower is better. Computed on held-out data, so it reflects rows the model didn't train on."
            />
          </dt>
          <dd>{m.rmse_cv === null || m.rmse_cv === undefined ? "—" : m.rmse_cv.toFixed(1)}</dd>
          <p className="hint">{model.target_unit ?? ""}</p>
        </div>
      </dl>

      <p className="muted small">
        Training R² {score(m.r2_train)}
        <InfoTip
          label="Training R²"
          text="How well the fit matches the exact rows it was trained on. With few rows and several coefficients this looks good almost automatically — it says nothing about predicting new data."
        />
        {" "}— not a measure of performance on this many points, shown only for
        completeness.
      </p>
      {m.cv_note && <p className="muted small">{m.cv_note}</p>}

      {model.equation ? (
        <>
          <h4>Equation</h4>
          <pre className="equation">{model.equation}</pre>
        </>
      ) : model.opaque ? (
        <p className="muted small">
          This engine has no closed form to publish — it is a stored estimator
          rather than an equation.
        </p>
      ) : (
        <div className="locked">
          <strong>The model itself is not shown.</strong> Contribute your
          measurements to this project to get access to its coefficients.
        </div>
      )}
    </article>
  );
}
