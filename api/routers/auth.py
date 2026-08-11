"""Registration, login, logout, and "who am I".

No email verification: it was skipped to avoid a dependency on institutional
SMTP during the build, and it is listed in ROADMAP.md as a blocker before open
registration goes live. The `email_verified` column already exists so that
adding the flow later is not a migration on a live table.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.config import settings
from api.db import get_db, utcnow
from api.deps import get_current_user, get_current_user_optional
from api.models import User
from api.schemas import LoginRequest, RegisterRequest, UserOut
from api.security import (
    SESSION_MAX_AGE,
    hash_password,
    make_session_token,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        settings.session_cookie,
        make_session_token(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,           # unreachable from JavaScript
        samesite="lax",          # front end and API share an origin here
        secure=not settings.is_development,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    # Emails are compared case-insensitively; "A@b.com" and "a@b.com" are one
    # account, and storing the lowercased form keeps the unique index honest.
    email = payload.email.lower()
    exists = db.scalar(select(User.id).where(func.lower(User.email) == email))
    if exists is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account already uses this email address."
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        institution=(payload.institution or None),
        country=(payload.country or None),
        last_login_at=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _set_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))

    # One message for "no such account" and for "wrong password", on purpose:
    # distinguishing them turns the login form into a way to test whether a
    # given researcher has an account here.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email address or password."
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)

    _set_session_cookie(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(settings.session_cookie, path="/")


@router.get("/me", response_model=UserOut | None)
def me(user: User | None = Depends(get_current_user_optional)):
    """Current user, or null. Never 401 — the front end calls this on every
    page load to decide what to render, including for signed-out visitors."""
    return user


@router.get("/session", response_model=UserOut)
def session_required(user: User = Depends(get_current_user)):
    """Same as /me but 401s. Useful for guarding a route from the client."""
    return user
