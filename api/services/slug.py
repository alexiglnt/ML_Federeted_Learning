"""URL slugs for projects.

Slugs are permanent once issued. A project page is the thing researchers cite
to each other and, eventually, in papers, so silently reissuing a slug when a
title is edited would break links that already exist in the wild.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

MAX_LENGTH = 90
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """"Residual stress in Ti-6Al-4V" -> "residual-stress-in-ti-6al-4v"."""
    ascii_text = (
        unicodedata.normalize("NFKD", str(text or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = _NON_SLUG.sub("-", ascii_text.lower()).strip("-")
    slug = slug[:MAX_LENGTH].strip("-")
    # A title made entirely of characters ASCII cannot represent leaves nothing
    # behind; the caller still needs a usable identifier.
    return slug or "project"


def unique_slug(base: str, exists: Callable[[str], bool]) -> str:
    """Append -2, -3 … until `exists` says the slug is free.

    Bounded rather than looping forever: past a few hundred collisions
    something is wrong upstream, and an unbounded loop against the database
    would hang the request instead of failing it.
    """
    slug = slugify(base)
    if not exists(slug):
        return slug
    for suffix in range(2, 500):
        candidate = f"{slug[: MAX_LENGTH - 5]}-{suffix}".strip("-")
        if not exists(candidate):
            return candidate
    raise RuntimeError(f"Could not find a free slug based on {slug!r}.")
