/* A small "(i)" next to a term, for the reader who knows the platform but not
 * what this particular number means today.
 *
 * The bubble is portalled to <body> and positioned with `fixed` coordinates
 * measured from the trigger, rather than CSS-absolute inside the normal flow.
 * Every table on this site sits in a `.table-scroll` div for the horizontal
 * scrollbar on narrow screens, and `overflow-x: auto` there makes the browser
 * clip vertical overflow too — a plain absolutely-positioned bubble gets cut
 * off the moment it's taller than the row it's anchored to. Escaping to a
 * fixed-position portal sidesteps that regardless of which ancestor scrolls.
 *
 * Position is measured once, when the bubble opens — it does not track
 * page scroll while open. Good enough for a hover tooltip that closes the
 * moment the pointer or focus moves.
 */

import { useState } from "react";
import { createPortal } from "react-dom";

let nextId = 0;

/** Stable per-instance id for aria-describedby. */
function makeId(seed: string): string {
  nextId += 1;
  return `info-tip-${seed.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-${nextId}`;
}

export default function InfoTip({ label, text }: { label: string; text: string }) {
  const [id] = useState(() => makeId(label));
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  function show(event: { currentTarget: HTMLButtonElement }) {
    const rect = event.currentTarget.getBoundingClientRect();
    setPos({ top: rect.bottom + 6, left: rect.left + rect.width / 2 });
    setOpen(true);
  }
  function hide() {
    setOpen(false);
  }

  return (
    <span className="info-tip">
      <button
        type="button"
        className="info-tip-trigger"
        aria-describedby={id}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(event) => (open ? hide() : show(event))}
        onKeyDown={(event) => event.key === "Escape" && hide()}
      >
        i<span className="visually-hidden">What is {label}?</span>
      </button>
      {open &&
        createPortal(
          <span
            role="tooltip"
            id={id}
            className="info-tip-bubble"
            style={{ top: pos.top, left: pos.left }}
          >
            {text}
          </span>,
          document.body,
        )}
    </span>
  );
}
