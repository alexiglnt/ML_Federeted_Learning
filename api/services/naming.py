"""Canonical form of a column or variable name.

Ported from `legacy/web/js/parse.js`, whose comments were in French. It is worth
keeping rather than rewriting: it encodes what real files from real labs
actually look like. Without the Greek table, "γ (°)" and "rβ (µm)" survive
neither normalisation nor matching, and those are the exact column headings in
the study this platform started from.

The same function runs in the browser (see the TypeScript port in the front
end) so that the preview a contributor sees matches what the server decides.
"""

from __future__ import annotations

import re
import unicodedata

GREEK = {
    "γ": "gamma", "β": "beta", "α": "alpha", "θ": "theta", "σ": "sigma",
    "τ": "tau", "λ": "lambda", "μ": "mu", "µ": "mu", "ρ": "rho", "φ": "phi",
    "ω": "omega", "Δ": "delta", "δ": "delta",
}

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_UNIT_IN_NAME = re.compile(r"[(\[]([^)\]]{1,20})[)\]]")


def normalise(name: str | None) -> str:
    """Accent-free, unit-free, punctuation-free lowercase form.

    "Vc (m/min)" -> "vc";  "γ (°)" -> "gamma";  "Rβ [µm]" -> "rbeta".
    """
    s = str(name or "")
    for greek, latin in GREEK.items():
        s = s.replace(greek, latin)
    s = _BRACKETED.sub(" ", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _NON_ALNUM.sub(" ", s.lower())
    return " ".join(s.split())


def extract_unit(name: str | None) -> str | None:
    """The unit written inside brackets in a column heading, if any.

    A disagreement between this and the expected unit is a strong signal that a
    column match is wrong — stronger than a good name match is that it is
    right. Used to warn rather than to reject, since plenty of headings carry
    no unit at all.
    """
    match = _UNIT_IN_NAME.search(str(name or ""))
    if not match:
        return None
    unit = match.group(1).strip()
    return unit or None


def similarity(a: str, b: str) -> float:
    """Crude 0..1 closeness of two already-normalised names.

    Token overlap (Jaccard), which handles "cutting speed" against "speed
    cutting" and the reorderings people actually produce. Deliberately not a
    fuzzy edit distance: near-miss spellings between *different* physical
    quantities are more dangerous here than a missed match, because a wrong
    match silently fits a model to the wrong column.
    """
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
