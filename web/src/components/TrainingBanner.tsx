/* What a training run is doing, while it does it.
 *
 * No progress bar on purpose: the server knows which phase it is in, not how
 * far through it, and a bar that crawls to 90% and sits there teaches people
 * to distrust it. A spinner, the phase the server reports, and the elapsed
 * time are all true.
 */

import { useEffect, useState } from "react";

import type { TrainingJobOut } from "../lib/api";

function elapsedSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const start = Date.parse(iso);
  return Number.isNaN(start) ? null : Math.max(0, Math.round((Date.now() - start) / 1000));
}

export default function TrainingBanner({ job }: { job: TrainingJobOut }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const queued = job.status === "queued";
  const seconds = elapsedSince(job.started_at ?? job.created_at);
  const phase = queued
    ? "Waiting for the previous run to finish…"
    : job.log ?? "Starting…";

  return (
    <div className="notice training-banner" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <div>
        <p>
          <strong>A new model version is being trained.</strong> {phase}
          {seconds !== null && <span className="muted small"> · {seconds}s</span>}
        </p>
        <p className="muted small">
          Every engine is refitted and scored on the same data, which usually
          takes under a minute. You can leave this page — the result will be
          here when you come back.
        </p>
      </div>
    </div>
  );
}
