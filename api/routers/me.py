"""The personal dashboard: what I've contributed, where I have access, and
what is waiting on my decision.

`Me.tsx` calls these three alongside the existing `GET /api/projects/mine`.
Each is a single joined query rather than N+1 per project, and each is
read-only — the actions themselves (review, withdraw, share) stay on the
project page, where the full context (the §5.3 scores, poolability) already
lives.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import settings
from api.db import get_db
from api.deps import get_current_user
from api.models import AccessRole, Contribution, ContributionStatus, Project, ProjectAccess, User
from api.schemas import (
    AccountDelete,
    MyAccessOut,
    MyContributionOut,
    MyReviewQueueItem,
    PasswordChange,
    ProfileUpdate,
    UserOut,
)
from api.security import hash_password, verify_password

router = APIRouter(prefix="/api/me", tags=["me"])


@router.patch("", response_model=UserOut)
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit my own name, institution, country. Email and password are not
    here — see ProfileUpdate's docstring."""
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.institution is not None:
        user.institution = payload.institution.strip() or None
    if payload.country is not None:
        user.country = payload.country.strip() or None
    db.commit()
    db.refresh(user)
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    payload: AccountDelete,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Anonymise my own account. Not a row-level DELETE.

    `contributions.contributor_id`, `project_access.user_id` and the audit
    log all reference `users.id` without ON DELETE CASCADE, on purpose — the
    record of who contributed what must not vanish just because they later
    close their account, or another owner's published model loses its own
    lineage. So this scrubs the identifying fields and locks the password
    instead of removing the row.

    Still owning a project blocks this, the same way it would block a real
    delete: the owner has to close or hand off each project first rather than
    leave it ownerless.
    """
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password.")

    still_owns = db.scalar(select(Project.id).where(Project.owner_id == user.id).limit(1))
    if still_owns is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You still own at least one project. Delete or hand it off first, "
            "from that project's settings.",
        )

    user.email = f"deleted-user-{user.id}@deleted.invalid"
    user.full_name = "Deleted user"
    user.institution = None
    user.country = None
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    db.commit()

    response.delete_cookie(settings.session_cookie, path="/")


@router.get("/contributions", response_model=list[MyContributionOut])
def my_contributions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(
        select(Contribution, Project.slug, Project.title)
        .join(Project, Project.id == Contribution.project_id)
        .where(Contribution.contributor_id == user.id)
        .order_by(Contribution.submitted_at.desc())
    ).all()
    return [
        MyContributionOut(
            id=contribution.id,
            project_slug=slug,
            project_title=title,
            mode=contribution.mode,
            status=contribution.status,
            n_rows=contribution.n_rows,
            submitted_at=contribution.submitted_at,
            reviewed_at=contribution.reviewed_at,
            review_note=contribution.review_note,
        )
        for contribution, slug, title in rows
    ]


@router.get("/access", response_model=list[MyAccessOut])
def my_access(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Projects I may use the model of. Owned projects are excluded — those
    are already listed under "Projects I own" via `GET /api/projects/mine`,
    and listing them again here would just duplicate that section."""
    rows = db.execute(
        select(ProjectAccess, Project.slug, Project.title)
        .join(Project, Project.id == ProjectAccess.project_id)
        .where(ProjectAccess.user_id == user.id, ProjectAccess.role != AccessRole.OWNER)
        .order_by(ProjectAccess.granted_at.desc())
    ).all()
    return [
        MyAccessOut(
            project_slug=slug,
            project_title=title,
            role=access.role.value,
            granted_at=access.granted_at,
        )
        for access, slug, title in rows
    ]


@router.get("/review-queue", response_model=list[MyReviewQueueItem])
def my_review_queue(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Pending contributions across every project I own — the same rows each
    project page shows in its review queue, gathered in one place."""
    rows = db.execute(
        select(Contribution, Project.slug, Project.title, User.full_name)
        .join(Project, Project.id == Contribution.project_id)
        .join(User, User.id == Contribution.contributor_id)
        .where(Project.owner_id == user.id, Contribution.status == ContributionStatus.PENDING)
        .order_by(Contribution.submitted_at)
    ).all()
    return [
        MyReviewQueueItem(
            project_slug=slug,
            project_title=title,
            contribution_id=contribution.id,
            contributor_name=contributor_name,
            mode=contribution.mode,
            n_rows=contribution.n_rows,
            submitted_at=contribution.submitted_at,
        )
        for contribution, slug, title, contributor_name in rows
    ]
