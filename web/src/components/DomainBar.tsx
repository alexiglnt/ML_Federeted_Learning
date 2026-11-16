/* Where one input is declared to apply, and where there is actually data.
 *
 * Three quantities on one axis, and the distinction between them is the whole
 * point of the drawing:
 *
 *   declared        what the owner said the project is about — a claim
 *   owner's data    where the owner's own measurements sit
 *   with contributions   how far other labs pushed that
 *
 * Only the second and third license belief in a prediction, which is why the
 * prediction page warns against the *covered* range and not the declared one.
 * And the gap between the owner's band and the full covered band is the
 * platform's reason to exist made visible: it is the part of the domain that
 * pooling bought.
 *
 * The SVG carries no text. It is stretched with preserveAspectRatio="none" so
 * the x axis is literally a percentage, and any text inside would be squashed
 * with it; the numbers live in HTML underneath, where they stay legible and
 * selectable.
 */

import type { ProjectInputOut } from "../lib/api";

type Span = [number, number];

/** A pair is only drawable when both ends are known. A half-declared range is
 *  reported in words below rather than guessed at. */
function span(min: number | null, max: number | null): Span | null {
  if (min === null || max === null) return null;
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  return min <= max ? [min, max] : [max, min];
}

function num(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "?";
  const size = Math.abs(value);
  if (size !== 0 && (size < 0.001 || size >= 100000)) return value.toExponential(1);
  return String(Math.round(value * 1000) / 1000);
}

function label(min: number | null, max: number | null): string {
  return `${num(min)} → ${num(max)}`;
}

/** Widths in viewBox units, which are percentages of the axis. */
const FULL = 100;
/** A band whose ends coincide — one measurement, or a declared point value —
 *  would otherwise be a zero-width rectangle, i.e. invisible. */
const MIN_BAND = 1.2;

export default function DomainBar({ input }: { input: ProjectInputOut }) {
  const declared = span(input.expected_min, input.expected_max);
  const covered = span(input.observed_min, input.observed_max);
  const owner = span(input.owner_min, input.owner_max);

  const known = [declared, covered].filter((item): item is Span => item !== null);
  if (known.length === 0) {
    return (
      <p className="muted small">
        No range declared and no data yet.
      </p>
    );
  }

  const low = Math.min(...known.map(([start]) => start));
  const high = Math.max(...known.map(([, end]) => end));
  // A single value has no extent to scale against, so give the axis one.
  const reach = high - low || Math.max(Math.abs(high) * 0.1, 1);
  const pad = reach * 0.06;
  const axisLow = low - pad;
  const axisHigh = high + pad;

  const x = (value: number) => ((value - axisLow) / (axisHigh - axisLow)) * FULL;
  const band = ([start, end]: Span) => {
    const left = x(start);
    return { x: left, width: Math.max(x(end) - left, MIN_BAND) };
  };

  // Said in words for anyone who cannot see the drawing, and it is also the
  // honest summary of it.
  const description = [
    declared ? `declared ${label(...declared)}` : "no declared range",
    covered ? `data covers ${label(...covered)}` : "no data yet",
  ].join(", ");

  const extended =
    covered !== null &&
    (owner === null || covered[0] < owner[0] || covered[1] > owner[1]);
  const beyondDeclared =
    covered !== null &&
    declared !== null &&
    (covered[0] < declared[0] || covered[1] > declared[1]);

  return (
    <div className="domain">
      <svg
        className="domain-svg"
        viewBox={`0 0 ${FULL} 22`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${input.variable.display_name}: ${description}`}
      >
        {/* Declared — the claim. */}
        <rect className="domain-track" x="0" y="0" width={FULL} height="8" />
        {declared && <rect className="domain-declared" y="0" height="8" {...band(declared)} />}

        {/* Evidence. The full covered span is painted first and the owner's own
            band over it, so what stays visible in the lighter colour is
            precisely what other labs added. */}
        <rect className="domain-track" x="0" y="14" width={FULL} height="8" />
        {covered && <rect className="domain-added" y="14" height="8" {...band(covered)} />}
        {owner && <rect className="domain-owner" y="14" height="8" {...band(owner)} />}
      </svg>

      <div className="domain-scale small muted" aria-hidden="true">
        <span>{num(axisLow)}</span>
        <span>{num(axisHigh)}</span>
      </div>

      <ul className="domain-facts small">
        <li>
          <span className="swatch declared" aria-hidden="true" />
          declared{" "}
          {input.expected_min === null && input.expected_max === null ? (
            <span className="muted">not declared</span>
          ) : (
            label(input.expected_min, input.expected_max)
          )}
        </li>
        {owner && (
          <li>
            <span className="swatch owner" aria-hidden="true" />
            owner’s data {label(...owner)}
          </li>
        )}
        {covered && extended && (
          <li>
            <span className="swatch added" aria-hidden="true" />
            with contributions {label(...covered)}
          </li>
        )}
        {!covered && (
          <li className="muted">
            <span className="swatch empty" aria-hidden="true" />
            no accepted data yet
          </li>
        )}
      </ul>

      {beyondDeclared && (
        <p className="muted small">
          Data reaches past the declared range — the project covers more than it
          claims.
        </p>
      )}
    </div>
  );
}
