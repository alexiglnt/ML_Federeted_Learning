"""Shared FastAPI dependencies: the current user, and project permissions.

The permission matrix implemented here is the one in ARCHITECTURE.md §4.1.
Keeping it in one place rather than scattering checks through the routers is
what makes it testable — and it is on the list of invariants worth a test,
because a leak here exposes unpublished measurements belonging to someone else.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import settings
from api.db import get_db
from api.models import (
    AccessRole,
    ContributionStatus,
    Project,
    ProjectAccess,
    User,
    UserRole,
)
from api.security import read_session_token


def get_current_user_optional(
    db: Session = Depends(get_db),
    session: str | None = Cookie(default=None, alias=settings.session_cookie),
) -> User | None:
    if not session:
        return None
    uid = read_session_token(session)
    if uid is None:
        return None
    return db.get(User, uid)


def get_current_user(
    user: User | None = Depends(get_current_user_optional),
) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


def require_moderator(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.MODERATOR, UserRole.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Moderators only.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrators only.")
    return user


# --------------------------------------------------------------------------- #
# Project permissions
# --------------------------------------------------------------------------- #
def load_project(db: Session, slug: str) -> Project:
    """Fetch a project by slug, or 404.

    Deliberately performs no visibility check. `unlisted` means "hidden from
    discovery", not "access controlled" — a link to it is meant to work for
    whoever receives it. Everything genuinely protected (the model itself,
    contributors' files) is gated by the role checks below, so that reading
    those checks tells you the whole story rather than half of it.
    """
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such project.")
    return project


def access_role(db: Session, project: Project, user: User | None) -> AccessRole | None:
    """The viewer's role on this project, or None if they have no grant."""
    if user is None:
        return None
    if project.owner_id == user.id:
        return AccessRole.OWNER
    row = db.scalar(
        select(ProjectAccess).where(
            ProjectAccess.project_id == project.id,
            ProjectAccess.user_id == user.id,
        )
    )
    return row.role if row else None


def can_use_model(role: AccessRole | None) -> bool:
    """May this viewer see coefficients and run predictions?

    Owners and accepted contributors only. This is the counterpart of having
    shared data — everyone else sees metrics but not the model itself, which is
    what gives a visitor a reason to contribute.
    """
    return role in (AccessRole.OWNER, AccessRole.CONTRIBUTOR, AccessRole.VIEWER)


def can_read_raw_data(role: AccessRole | None) -> bool:
    """May this viewer read contributors' uploaded files? Owner alone.

    A contributor never sees another contributor's file. This is the promise
    the platform makes to people handing over unpublished measurements.
    """
    return role == AccessRole.OWNER


def require_project_owner(db: Session, project: Project, user: User) -> None:
    if project.owner_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the project owner can do this."
        )


def grant_contributor_access(
    db: Session, project: Project, user_id: int, contribution_id: int
) -> None:
    """Give a contributor model access, on acceptance of a shared contribution.

    Deliberately not called at submission time: see ProjectAccess's docstring.
    Idempotent, because a second accepted contribution from the same person
    must not fail.
    """
    existing = db.scalar(
        select(ProjectAccess).where(
            ProjectAccess.project_id == project.id,
            ProjectAccess.user_id == user_id,
        )
    )
    if existing is not None:
        return
    db.add(
        ProjectAccess(
            project_id=project.id,
            user_id=user_id,
            role=AccessRole.CONTRIBUTOR,
            source_contribution_id=contribution_id,
        )
    )


def revoke_contributor_access_if_unearned(
    db: Session, project: Project, user_id: int
) -> None:
    """Drop model access when a user no longer has any accepted shared data.

    Called after a rejection or a withdrawal. Without it, a contributor could
    unlock a model and then pull their data back out, which is exactly the
    free-ride the review step exists to prevent.
    """
    from api.models import Contribution, ContributionMode  # local: avoid a cycle

    still_earned = db.scalar(
        select(Contribution.id).where(
            Contribution.project_id == project.id,
            Contribution.contributor_id == user_id,
            Contribution.mode == ContributionMode.SHARED,
            Contribution.status == ContributionStatus.ACCEPTED,
        )
    )
    if still_earned is not None:
        return
    row = db.scalar(
        select(ProjectAccess).where(
            ProjectAccess.project_id == project.id,
            ProjectAccess.user_id == user_id,
            ProjectAccess.role == AccessRole.CONTRIBUTOR,
        )
    )
    if row is not None:
        db.delete(row)
