/* One contribution awaiting a decision, with the two scores read correctly.
 *
 * The reading guide on this card is not decoration. The tempting mistake is to
 * treat a poor transfer score as a verdict and reject — but transfer poor with
 * refit good means clean data from a regime the model does not cover, which is
 * the most valuable contribution the platform can receive, because it is what
 * extends the validity domain. Rejecting those is how this platform would
 * quietly become a place where everyone's model only works where it already
 * worked. So the card states the interpretation next to the numbers rather
 * than leaving it in a document nobody has open.
 *
 * See ARCHITECTURE.md §5.3.
 */

import { useState } from "react";

import type { ContributionOut, PoolabilityScore } from "../lib/api";

function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(3);
}

function delta(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(3)}`;
}

/** Deliberately coarse. These are read as "is this good, bad, or worth a look",
 *  and a finer scale would suggest a precision the numbers do not have on the
 *  handful of rows typical here. */
function verdict(value: number | null | undefined): "good" | "weak" | "poor" | "unknown" {
  if (value === null || value === undefined) return "unknown";
  if (value >= 0.7) return "good";
  if (value >= 0.3) return "weak";
  return "poor";
}

function Reading({ transfer, refit }: { transfer: number | null; refit: number | null }) {
  const t = verdict(transfer);
  const r = verdict(refit);

  if (t === "unknown" && r === "unknown") return null;
  if (t === "unknown") {
    return (
      <p className="reading">
        There was no published model to test against when this arrived, so only
        the refit score says anything. It reports whether these measurements are
        internally consistent.
      </p>
    );
  }
  if (t === "good") {
    return (
      <p className="reading good">
        <strong>Consistent with the data already here.</strong> The existing
        model predicts these measurements without being refitted.
      </p>
    );
  }
  if (r === "good") {
    return (
      <p className="reading valuable">
        <strong>Clean data from a regime the model does not cover.</strong> The
        measurements are highly predictable on their own, but the published
        model does not reach them. This is the most valuable kind of
        contribution there is — it extends the validity domain. Do not reject it
        for the poor transfer score.
      </p>
    );
  }
  if (r === "poor") {
    return (
      <p className="reading poor">
        <strong>Worth a hard look.</strong> The model does not predict this
        data, and neither does a model fitted on the data itself. That pattern
        is what noise looks like.
      </p>
    );
  }
  return (
    <p className="reading">
      Mixed. The published model does not transfer well and a fit on this data
      alone is only moderate. Ask what changed between the two benches — the
      measurement method is a common answer.
    </p>
  );
}

/** Thresholds for a *change* in leave-one-lab-out R², not an R² itself — a
 *  small negative delta is normal sampling noise, but the article's own
 *  running example (0.61 -> -4.86, Fig. 4) is what "poor" is calibrated to
 *  catch. */
function deltaVerdict(value: number | null | undefined): "good" | "weak" | "poor" | "unknown" {
  if (value === null || value === undefined) return "unknown";
  if (value >= -0.02) return "good";
  if (value >= -0.15) return "weak";
  return "poor";
}

function PoolabilityReading({
  ownR2,
  poolDelta,
}: {
  ownR2: number | null;
  poolDelta: number | null;
}) {
  const own = verdict(ownR2);
  const effect = deltaVerdict(poolDelta);

  if (own === "unknown" && effect === "unknown") return null;
  if (own === "poor" && effect === "poor") {
    return (
      <p className="reading poor">
        <strong>Looks like an outlier.</strong> A model trained on every other
        accepted contributor does not predict this lab's data, and accepting
        it would pull down the model's honest score for every other lab too —
        not just fail to fit on its own. Worth a hard look before accepting.
      </p>
    );
  }
  if (own === "poor") {
    return (
      <p className="reading">
        This lab's data is hard to predict from everyone else's, but
        accepting it would not meaningfully change the shared model's honest
        score elsewhere — the risk stays contained to this lab's own
        predictions.
      </p>
    );
  }
  if (own === "good" && effect !== "poor") {
    return (
      <p className="reading good">
        <strong>Pools cleanly.</strong> Everyone else's data already predicts
        this lab, and accepting it does not weaken the model's honest score
        for anyone else.
      </p>
    );
  }
  return (
    <p className="reading">
      Mixed — check the numbers per target below before deciding.
    </p>
  );
}

export default function ReviewCard({
  contribution,
  onDecide,
  onDownload,
  onCheckPoolability,
  busy,
}: {
  contribution: ContributionOut;
  onDecide: (decision: "accept" | "reject", note: string) => void;
  onDownload: () => void;
  onCheckPoolability: () => Promise<PoolabilityScore>;
  busy: boolean;
}) {
  const [note, setNote] = useState("");
  const [poolability, setPoolability] = useState<PoolabilityScore | null>(null);
  const [checkingPoolability, setCheckingPoolability] = useState(false);
  const [poolabilityError, setPoolabilityError] = useState<string | null>(null);

  async function handleCheckPoolability() {
    setCheckingPoolability(true);
    setPoolabilityError(null);
    try {
      setPoolability(await onCheckPoolability());
    } catch (caught) {
      setPoolabilityError(
        caught instanceof Error ? caught.message : "Could not check poolability.",
      );
    } finally {
      setCheckingPoolability(false);
    }
  }
  const transfer = contribution.transfer_score;
  const refit = contribution.refit_score;
  const targets = Array.from(
    new Set([
      ...Object.keys(transfer?.per_target ?? {}),
      ...Object.keys(refit?.per_target ?? {}),
    ]),
  );

  // The guide reads on the worst target rather than the best: a contribution is
  // only as trustworthy as its weakest quantity, and averaging would hide a
  // target that is pure noise behind one that is fine.
  const refitOf = (key: string) => {
    const entry = refit?.per_target?.[key];
    return entry?.r2_cv ?? entry?.r2_train;
  };

  const worst = (pick: (key: string) => number | null | undefined): number | null => {
    const values = targets
      .map(pick)
      .filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v));
    return values.length ? Math.min(...values) : null;
  };

  return (
    <article className="review-card">
      <header className="page-head">
        <h3>
          {contribution.contributor_name}
          <span className="muted small"> · {contribution.n_rows} rows</span>
        </h3>
        <span className="badge warn">awaiting review</span>
      </header>

      <p className="meta-line small">
        <span>{new Date(contribution.submitted_at).toLocaleDateString()}</span>
        {contribution.measurement_method && (
          <span>measured by {contribution.measurement_method}</span>
        )}
        {contribution.mode === "federated" && (
          <span className="badge">summary statistics only</span>
        )}
        {contribution.original_filename && (
          <button type="button" className="ghost tiny-button" onClick={onDownload}>
            Download {contribution.original_filename}
          </button>
        )}
      </p>

      {contribution.notes && <p className="lead small">“{contribution.notes}”</p>}

      {targets.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Target</th>
                <th scope="col">
                  Transfer R²
                  <br />
                  <span className="hint">our model, unchanged</span>
                </th>
                <th scope="col">
                  Refit R²
                  <br />
                  <span className="hint">their data alone, cross-validated</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {targets.map((key) => {
                const t = transfer?.per_target?.[key];
                const r = refit?.per_target?.[key];
                return (
                  <tr key={key}>
                    <td>
                      <code className="small">{key}</code>
                    </td>
                    <td className={`score-cell ${verdict(t?.r2)}`}>
                      {t?.error ? <span className="muted small">{t.error}</span> : score(t?.r2)}
                    </td>
                    {/* A federated contribution has no cross-validated refit:
                        leave-one-out removes points one at a time and summed
                        statistics cannot. The training score is shown instead,
                        labelled, rather than an empty cell. */}
                    <td className={`score-cell ${verdict(r?.r2_cv ?? r?.r2_train)}`}>
                      {r?.error ? (
                        <span className="muted small">{r.error}</span>
                      ) : (
                        <>
                          {score(r?.r2_cv ?? r?.r2_train)}
                          {r?.r2_cv === undefined && r?.r2_train !== undefined && (
                            <>
                              <br />
                              <span className="hint">training only</span>
                            </>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {transfer?.note && <p className="muted small">{transfer.note}</p>}
      {transfer?.version !== null && transfer?.version !== undefined && (
        <p className="muted small">
          Transfer measured against v{transfer.version}, the model published
          when this contribution arrived.
        </p>
      )}

      {refit?.note && <p className="muted small">{refit.note}</p>}

      <Reading
        transfer={worst((key) => transfer?.per_target?.[key]?.r2)}
        refit={worst(refitOf)}
      />

      {contribution.mode === "shared" ? (
        <div className="poolability">
          {!poolability && (
            <button
              type="button"
              className="ghost tiny-button"
              disabled={checkingPoolability}
              onClick={handleCheckPoolability}
            >
              {checkingPoolability
                ? "Checking…"
                : "Check poolability — does accepting this help or hurt the model?"}
            </button>
          )}
          {poolabilityError && <p className="muted small">{poolabilityError}</p>}

          {poolability && Object.keys(poolability.per_target).length > 0 && (
            <>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Target</th>
                      <th scope="col">
                        Held-out fit
                        <br />
                        <span className="hint">everyone else predicts this lab</span>
                      </th>
                      <th scope="col">
                        Pool effect
                        <br />
                        <span className="hint">honest R² if accepted</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(poolability.per_target).map(([key, entry]) => (
                      <tr key={key}>
                        <td>
                          <code className="small">{key}</code>
                        </td>
                        <td className={`score-cell ${verdict(entry.own_r2)}`}>
                          {entry.error ? (
                            <span className="muted small">{entry.error}</span>
                          ) : entry.note ? (
                            <span className="muted small">{entry.note}</span>
                          ) : (
                            score(entry.own_r2)
                          )}
                        </td>
                        <td className={`score-cell ${deltaVerdict(entry.pool_delta)}`}>
                          {entry.error || entry.note ? (
                            "—"
                          ) : (
                            <>
                              {score(entry.pool_r2_before)} → {score(entry.pool_r2_after)}
                              <br />
                              <span className="hint">{delta(entry.pool_delta)}</span>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <PoolabilityReading
                ownR2={(() => {
                  const values = Object.values(poolability.per_target)
                    .map((entry) => entry.own_r2)
                    .filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v));
                  return values.length ? Math.min(...values) : null;
                })()}
                poolDelta={(() => {
                  const values = Object.values(poolability.per_target)
                    .map((entry) => entry.pool_delta)
                    .filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v));
                  return values.length ? Math.min(...values) : null;
                })()}
              />
            </>
          )}
        </div>
      ) : (
        <p className="muted small">
          Poolability can't be checked for federated contributions — the
          server never sees the raw rows needed to hold this contributor's
          data out and test whether the model still predicts it.
        </p>
      )}

      <div className="field-row wide">
        <label htmlFor={`note-${contribution.id}`}>
          Note <span className="hint">recorded with the decision, seen by the contributor</span>
        </label>
        <textarea
          id={`note-${contribution.id}`}
          rows={2}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>

      <div className="cta-row">
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => onDecide("accept", note)}
        >
          Accept — adds the data and unlocks the model for them
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy}
          onClick={() => onDecide("reject", note)}
        >
          Reject
        </button>
      </div>
    </article>
  );
}
