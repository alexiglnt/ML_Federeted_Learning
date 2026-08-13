"""Creating the notifications that close ROADMAP.md's biggest gap.

Without these, an owner learns of a pending contribution only by visiting the
project page, and a contributor learns of a decision the same way — a
contribution can sit unseen indefinitely. Scope is deliberately narrow: only
the contribution-review loop fires a notification, because that is the loop
with the sharpest incentive problem (§4.2) and the one ROADMAP.md names.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.models import Contribution, ContributionStatus, Notification, NotificationKind, Project, User


def _add(
    db: Session,
    *,
    recipient_id: int,
    actor_id: int | None,
    kind: NotificationKind,
    project: Project,
    contribution: Contribution,
    title: str,
    body: str,
) -> None:
    # An owner's own contribution is auto-accepted (uploads.py); notifying
    # someone of their own action would just be noise.
    if recipient_id == actor_id:
        return
    db.add(
        Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            kind=kind,
            project_id=project.id,
            contribution_id=contribution.id,
            title=title,
            body=body,
        )
    )


def notify_contribution_submitted(
    db: Session, project: Project, contribution: Contribution, contributor_name: str
) -> None:
    """Tell the owner a contribution is waiting on them."""
    _add(
        db,
        recipient_id=project.owner_id,
        actor_id=contribution.contributor_id,
        kind=NotificationKind.CONTRIBUTION_SUBMITTED,
        project=project,
        contribution=contribution,
        title=f"New contribution to {project.title}",
        body=f"{contributor_name} submitted {contribution.n_rows} rows for review.",
    )


def notify_review_decision(
    db: Session, project: Project, contribution: Contribution, actor: User
) -> None:
    """Tell the contributor what the owner decided.

    Reads the outcome off `contribution.status`, which the caller must have
    already set to its new value.
    """
    accepted = contribution.status == ContributionStatus.ACCEPTED
    kind = (
        NotificationKind.CONTRIBUTION_ACCEPTED
        if accepted
        else NotificationKind.CONTRIBUTION_REJECTED
    )
    verb = "accepted" if accepted else "rejected"
    body = f"Your contribution of {contribution.n_rows} rows to {project.title} was {verb}."
    if contribution.review_note:
        body += f' Note: "{contribution.review_note}"'

    _add(
        db,
        recipient_id=contribution.contributor_id,
        actor_id=actor.id,
        kind=kind,
        project=project,
        contribution=contribution,
        title=f"Contribution {verb} — {project.title}",
        body=body,
    )
