"""Password hashing and signed session cookies.

Sessions rather than JWTs, on purpose. A JWT cannot be revoked before it
expires without keeping server-side state anyway, and the front end and the API
are served from the same origin here, so there is no cross-domain problem for a
cookie to solve. A signed cookie holding a user id is the smaller thing that
works, and `HttpOnly` keeps it out of reach of any script on the page.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from api.config import settings

# Argon2id, the current password-hashing recommendation, with the library's
# defaults — they are deliberately chosen to be sane and to move over time.
_hasher = PasswordHasher()

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="mlfl-session")

SESSION_MAX_AGE = settings.session_max_age_days * 24 * 3600


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than we now use.

    Argon2's defaults harden as the library is updated; rehashing on a
    successful login upgrades existing accounts without asking anyone to change
    their password.
    """
    return _hasher.check_needs_rehash(password_hash)


def make_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    """Return the user id, or None if the cookie is absent, stale or forged."""
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None
