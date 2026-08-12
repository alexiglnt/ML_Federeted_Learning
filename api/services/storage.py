"""Where uploaded files live, and how a two-step upload holds one in between.

Files are written under `settings.data_dir`, which is a Docker volume outside
the image and outside anything the web server serves. Nothing is ever stored
under a path derived from a user-supplied filename: the stored name is random,
and the original is kept only as a label in the database. That closes path
traversal by construction rather than by sanitising, which is the kind of
defence that survives someone editing this file later.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.config import settings

#: How long a parsed-but-unconfirmed upload stays available while the user
#: sorts out the column mapping. Long enough to be unhurried, short enough that
#: abandoned files are not kept indefinitely.
STAGING_MAX_AGE = 2 * 3600

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="mlfl-upload")

_SAFE_LABEL = re.compile(r"[^A-Za-z0-9._ -]")


def clean_label(filename: str) -> str:
    """A display-safe version of the original name. Never used as a path."""
    name = _SAFE_LABEL.sub("_", (filename or "").strip()) or "upload"
    return name[:200]


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _staging_path(token_id: str) -> Path:
    return settings.upload_dir / "staging" / f"{token_id}.bin"


def stash(data: bytes, *, project_id: int, user_id: int, filename: str) -> str:
    """Write a just-uploaded file aside and return a signed claim ticket.

    The ticket carries the project and the user it belongs to, and it is
    signed, so it cannot be edited to claim somebody else's staged file. The
    file on disk is named after a random id, never after anything the uploader
    chose.
    """
    token_id = secrets.token_urlsafe(24)
    path = _staging_path(token_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _serializer.dumps(
        {
            "id": token_id,
            "project_id": project_id,
            "user_id": user_id,
            "filename": clean_label(filename),
        }
    )


def claim(token: str, *, project_id: int, user_id: int) -> tuple[bytes, str]:
    """Read back a staged file, checking it belongs to this user and project.

    Raises `LookupError` with a message meant for the uploader.
    """
    try:
        payload = _serializer.loads(token, max_age=STAGING_MAX_AGE)
    except SignatureExpired as error:
        raise LookupError(
            "This upload has expired. Please choose the file again."
        ) from error
    except BadSignature as error:
        raise LookupError("This upload reference is not valid.") from error

    if payload.get("project_id") != project_id or payload.get("user_id") != user_id:
        raise LookupError("This upload belongs to a different project or user.")

    path = _staging_path(str(payload.get("id", "")))
    if not path.is_file():
        raise LookupError(
            "The staged file is no longer on the server. Please upload it again."
        )
    return path.read_bytes(), str(payload.get("filename") or "upload")


def discard(token: str) -> None:
    """Best-effort removal of a staged file once it has been committed."""
    try:
        payload = _serializer.loads(token, max_age=STAGING_MAX_AGE)
        _staging_path(str(payload.get("id", ""))).unlink(missing_ok=True)
    except (BadSignature, SignatureExpired, OSError):
        pass


def store_dataset(data: bytes, *, project_id: int, suffix: str) -> Path:
    """Move a confirmed upload into permanent storage, keyed by content hash.

    Naming by hash means the same file submitted twice occupies one blob, and
    it gives an integrity check for free. Files are grouped per project so that
    deleting a project's data is a directory operation.
    """
    digest = content_hash(data)
    directory = settings.upload_dir / "projects" / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return path


def relative_path(path: Path) -> str:
    """Path stored in the database, relative to the data directory.

    Relative on purpose: an absolute path baked into rows would break the day
    the volume is mounted somewhere else.
    """
    try:
        return str(path.relative_to(settings.data_dir))
    except ValueError:
        return str(path)


_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _needs_escaping(cell: str) -> bool:
    """Would this cell run as a formula if the file were opened in Excel?

    The naive rule — "escape anything starting with = + - @" — corrupts
    ordinary data, because a residual stress of `-454.0` starts with a minus
    sign and is exactly the kind of value this platform carries. So a cell is
    escaped only when it leads with a formula character **and** is not a
    number. That neutralises `=cmd|'/c calc'!A1` while leaving every
    measurement untouched.
    """
    stripped = cell.lstrip()
    if not stripped.startswith(_FORMULA_LEAD):
        return False
    try:
        float(stripped.replace(",", "."))
    except ValueError:
        return True
    return False


def sanitise_csv(data: bytes) -> bytes:
    """Neutralise formula injection in a CSV about to be handed to someone.

    Spreadsheet software executes a cell beginning with `=` when the file is
    opened, so a contributor could otherwise hand the project owner a payload
    that runs on their machine the moment they inspect the data. Escaped cells
    are prefixed with an apostrophe, the conventional "this is text" marker.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Not decodable as UTF-8: leave it alone rather than mangle bytes we
        # do not understand. The download headers still force a save.
        return data

    out_lines = []
    changed = False
    for line in text.splitlines():
        cells = line.split(",")
        for index, cell in enumerate(cells):
            if _needs_escaping(cell):
                cells[index] = "'" + cell
                changed = True
        out_lines.append(",".join(cells))
    if not changed:
        return data
    return ("\n".join(out_lines) + "\n").encode("utf-8")


def absolute_path(stored: str) -> Path:
    """Resolve a stored path, refusing anything that escapes the data dir.

    A row is not a trusted input: it may have been written by older code, or by
    a bug. Re-checking here means a bad value cannot be turned into an
    arbitrary file read.
    """
    candidate = (settings.data_dir / stored).resolve()
    root = settings.data_dir.resolve()
    if not candidate.is_relative_to(root):
        raise LookupError("Refusing to read a file outside the data directory.")
    return candidate
