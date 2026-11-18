"""The data model, in the same order as ARCHITECTURE.md §6.

Read that section alongside this file. The two warnings it carries — §5.4 on
why every project trains two model tracks, and §5.5 on the double-counting trap
when a contribution changes mode — describe failures that are silent rather
than loud, and both are enforced partly here and partly in the services.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base, TZDateTime, utcnow


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Store enums by their *value*, not their Python attribute name.

    `native_enum=False` keeps them as a constrained VARCHAR rather than a
    Postgres ENUM type: adding a variant later is then an ordinary migration
    instead of an `ALTER TYPE` dance.
    """
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class UserRole(str, enum.Enum):
    USER = "user"
    MODERATOR = "moderator"      # may approve proposed registry variables
    ADMIN = "admin"


class VariableKind(str, enum.Enum):
    CONTINUOUS = "continuous"
    CATEGORICAL = "categorical"  # schema-ready; not implemented in v1 (§6.1)


class VariableStatus(str, enum.Enum):
    APPROVED = "approved"        # in the shared registry
    PROPOSED = "proposed"        # usable by its author, awaiting moderation
    REJECTED = "rejected"


class ProjectVisibility(str, enum.Enum):
    PUBLIC = "public"
    UNLISTED = "unlisted"        # reachable by link, absent from discovery


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"              # created, no initial data yet
    ACTIVE = "active"
    ARCHIVED = "archived"        # no longer accepting contributions


class Engine(str, enum.Enum):
    LINEAR = "linear"
    RIDGE = "ridge"
    PIML = "piml"
    GPR = "gpr"
    GBM = "gbm"
    RF = "rf"

    @property
    def is_federated_compatible(self) -> bool:
        """Can this engine be fitted from summed sufficient statistics alone?

        True exactly when the loss is quadratic in the coefficients, which is
        what makes `D'D`, `D'y`, `y'y`, `n` a sufficient summary of the data.
        GPR, boosting and forests need the individual rows and no summary
        replaces them — hence the two-track design in ARCHITECTURE.md §5.4.
        """
        return self in (Engine.LINEAR, Engine.RIDGE, Engine.PIML)


#: Engines the reference track may use. The reference model is the one every
#: contributor feeds, including federated ones, so it is confined to the
#: federated-compatible family by construction.
REFERENCE_ENGINES = tuple(e for e in Engine if e.is_federated_compatible)


class ContributionMode(str, enum.Enum):
    SHARED = "shared"            # raw file uploaded; unlocks model access
    FEDERATED = "federated"      # sufficient statistics only; no model access


class ContributionStatus(str, enum.Enum):
    PENDING = "pending"          # awaiting owner review (§4.2)
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"      # pulled by the contributor


class ModelTrack(str, enum.Enum):
    REFERENCE = "reference"      # all data, linear family
    MAIN = "main"                # shared data only, owner's chosen engine


class AccessRole(str, enum.Enum):
    OWNER = "owner"
    CONTRIBUTOR = "contributor"  # may use the model, never sees others' files
    VIEWER = "viewer"            # explicitly invited read access


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    institution: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole, "user_role"), default=UserRole.USER
    )
    # No verification flow is implemented — see ROADMAP.md. The column exists
    # so that adding one later does not require a migration on a live table.
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    projects: Mapped[list[Project]] = relationship(back_populates="owner")
    contributions: Mapped[list[Contribution]] = relationship(
        back_populates="contributor", foreign_keys="Contribution.contributor_id"
    )


# --------------------------------------------------------------------------- #
# The variable registry (ARCHITECTURE.md §3)
# --------------------------------------------------------------------------- #
class Variable(Base):
    """A canonical physical quantity.

    Projects pick their inputs from here rather than naming them freely. That
    is what makes discovery by input variable exact, unit conversion possible,
    and column matching against an uploaded file reliable.
    """

    __tablename__ = "variables"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    symbol: Mapped[str | None] = mapped_column(String(24))

    #: Canonical unit. A project may declare a different one for its own data;
    #: conversion happens on the way in.
    unit: Mapped[str | None] = mapped_column(String(40))
    #: Physical dimension ("speed", "length", "angle", "stress"…). Two
    #: variables can only be unit-converted into each other within a dimension,
    #: and a dimension mismatch is a strong signal that a column match is wrong.
    dimension: Mapped[str | None] = mapped_column(String(40), index=True)

    kind: Mapped[VariableKind] = mapped_column(
        _enum(VariableKind, "variable_kind"), default=VariableKind.CONTINUOUS
    )
    #: Frozen category list for categorical variables. Freezing matters: if two
    #: contributors one-hot encode in different orders their sufficient
    #: statistics stop being addable and the reference model silently corrupts.
    #: See ARCHITECTURE.md §6.1.
    categories: Mapped[list | None] = mapped_column(JSONB)

    #: A *suggested* default for the PIML physical prior — see
    #: `ProjectInput.penalised_sign`, which is the authoritative value. Only a
    #: suggestion because the prior is a statement about an (input, target)
    #: pair: "raising cutting speed makes residual stress less compressive"
    #: says nothing about cutting speed on its own. Used to pre-fill the
    #: project creation form, never to fit anything.
    penalised_sign: Mapped[float | None] = mapped_column(Float)

    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[VariableStatus] = mapped_column(
        _enum(VariableStatus, "variable_status"),
        default=VariableStatus.PROPOSED,
        index=True,
    )
    proposed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    aliases: Mapped[list[VariableAlias]] = relationship(
        back_populates="variable", cascade="all, delete-orphan"
    )


class VariableAlias(Base):
    """Alternative spellings, stored in normalised form.

    Feeds column matching against uploaded files: "Vc (m/min)", "cutting
    speed", "vitesse de coupe" all normalise onto the same variable. Seeded
    from the original site's hint table and extended whenever a user accepts a
    suggested match.
    """

    __tablename__ = "variable_aliases"
    __table_args__ = (UniqueConstraint("variable_id", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    variable_id: Mapped[int] = mapped_column(
        ForeignKey("variables.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(40), default="seed")

    variable: Mapped[Variable] = relationship(back_populates="aliases")


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    material: Mapped[str | None] = mapped_column(String(120), index=True)
    process: Mapped[str | None] = mapped_column(String(120), index=True)

    visibility: Mapped[ProjectVisibility] = mapped_column(
        _enum(ProjectVisibility, "project_visibility"),
        default=ProjectVisibility.PUBLIC,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus, "project_status"), default=ProjectStatus.DRAFT
    )

    #: Engine for the *main* track. The reference track is always fitted from
    #: REFERENCE_ENGINES regardless of this.
    main_engine: Mapped[Engine] = mapped_column(
        _enum(Engine, "engine"), default=Engine.PIML
    )
    #: Whether the project takes federated contributions at all. Always true in
    #: practice because the reference track can absorb them whatever the main
    #: engine is; kept as a column so an owner can opt out.
    accepts_federated: Mapped[bool] = mapped_column(Boolean, default=True)

    licence: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=utcnow, onupdate=utcnow
    )

    owner: Mapped[User] = relationship(back_populates="projects")
    inputs: Mapped[list[ProjectInput]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectInput.position",
    )
    targets: Mapped[list[ProjectTarget]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectTarget.position",
    )
    contributions: Mapped[list[Contribution]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    versions: Mapped[list[ModelVersion]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ModelVersion.number",
    )


class ProjectInput(Base):
    """One declared input of a project.

    `position` is part of the contract, not decoration: a contribution whose
    columns are permuted produces silently wrong coefficients. The original
    server rejected any contribution whose feature order disagreed with the
    model's, and that check is preserved.
    """

    __tablename__ = "project_inputs"
    __table_args__ = (
        UniqueConstraint("project_id", "variable_id"),
        UniqueConstraint("project_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    #: PIML physical prior: the *forbidden* sign of this input's coefficient.
    #: -1 discourages a negative coefficient, +1 a positive one, NULL means no
    #: prior. The penalty is `lam * sum(max(0, penalised_sign * coef)^2)`, so
    #: it is a soft push, not a hard constraint — a strongly contradicted prior
    #: still yields a nonzero coefficient of the "forbidden" sign.
    #:
    #: Lives here rather than on the variable because the prior concerns an
    #: (input, target) pair. Applying one sign across all of a project's
    #: targets is a simplification, and the same one the original single-model
    #: site made: its `penalised_sign` was shared by SRS_L and SRS_T, which are
    #: physically alike. A project whose targets behave oppositely would need
    #: this per target — see ROADMAP.md.
    penalised_sign: Mapped[float | None] = mapped_column(Float)

    #: Unit this project's own data is expressed in; may differ from the
    #: variable's canonical unit, in which case values are converted on entry.
    unit: Mapped[str | None] = mapped_column(String(40))
    #: Declared expected range, informational — used to warn a contributor that
    #: their data sits outside the domain, never to reject it. Data outside the
    #: domain is how a model's validity domain grows.
    expected_min: Mapped[float | None] = mapped_column(Float)
    expected_max: Mapped[float | None] = mapped_column(Float)

    project: Mapped[Project] = relationship(back_populates="inputs")
    variable: Mapped[Variable] = relationship()


class ProjectTarget(Base):
    """A quantity the project predicts. A project may have several."""

    __tablename__ = "project_targets"
    __table_args__ = (
        UniqueConstraint("project_id", "variable_id"),
        UniqueConstraint("project_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str | None] = mapped_column(String(40))

    project: Mapped[Project] = relationship(back_populates="targets")
    variable: Mapped[Variable] = relationship()


# --------------------------------------------------------------------------- #
# Contributions
# --------------------------------------------------------------------------- #
class Contribution(Base):
    """One submission by one user to one project.

    ⚠️ A contribution that switches from federated to shared stays **this same
    row**, with `mode` changed. It must never become a second row: the data
    would then enter the reference model twice, once through the sums and once
    through the rows, and nothing would look broken. The switch has to subtract
    the sufficient statistics before adding the raw rows. See
    ARCHITECTURE.md §5.5 — there is a test for this.
    """

    __tablename__ = "contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    contributor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    mode: Mapped[ContributionMode] = mapped_column(_enum(ContributionMode, "contribution_mode"))
    status: Mapped[ContributionStatus] = mapped_column(
        _enum(ContributionStatus, "contribution_status"),
        default=ContributionStatus.PENDING,
        index=True,
    )

    n_rows: Mapped[int] = mapped_column(Integer)
    #: Residual-stress values from XRD and from hole drilling differ by tens of
    #: MPa on the same part. Pooling two conventions unknowingly would fit a
    #: model to their average, so the method is recorded and shown at review.
    measurement_method: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)

    #: {variable_key: [min, max]} — the only description of the inputs that a
    #: federated contribution discloses, and what grows the validity domain.
    feature_ranges: Mapped[dict | None] = mapped_column(JSONB)

    #: The two scores of ARCHITECTURE.md §5.3, shown to the owner at review.
    #: Poor transfer with good refit is a *good* contribution, not a bad one.
    transfer_score: Mapped[dict | None] = mapped_column(JSONB)
    refit_score: Mapped[dict | None] = mapped_column(JSONB)

    submitted_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="contributions")
    contributor: Mapped[User] = relationship(
        back_populates="contributions", foreign_keys=[contributor_id]
    )
    dataset: Mapped[Dataset | None] = relationship(
        back_populates="contribution", cascade="all, delete-orphan", uselist=False
    )
    federated_stats: Mapped[list[FederatedStats]] = relationship(
        back_populates="contribution", cascade="all, delete-orphan"
    )


class Dataset(Base):
    """The uploaded file behind a *shared* contribution.

    Only the project owner may read it. The file itself lives on disk under
    `settings.upload_dir`, outside any directory the web server serves.
    """

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    contribution_id: Mapped[int] = mapped_column(
        ForeignKey("contributions.id", ondelete="CASCADE"), unique=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    #: SHA-256 of the file, used to spot the same measurements submitted twice
    #: to one project — which would double their weight in the fit.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    n_rows: Mapped[int] = mapped_column(Integer)
    n_cols: Mapped[int] = mapped_column(Integer)
    #: {variable_key: source column name} as confirmed by the contributor.
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)
    #: Separator, decimal mark, header row, dropped rows — kept so a puzzling
    #: fit can be traced back to how the file was read.
    parse_report: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    contribution: Mapped[Contribution] = relationship(back_populates="dataset")


class FederatedStats(Base):
    """Sufficient statistics behind a *federated* contribution, per target.

    `D'D`, `D'y`, `y'y` and `n` with `D = [1, X]`. These four are additive
    across labs and reconstruct a quadratic loss exactly, which is what makes
    federated aggregation an exact refit rather than a weight average. See
    ARCHITECTURE.md §5.1.
    """

    __tablename__ = "federated_stats"
    __table_args__ = (UniqueConstraint("contribution_id", "target_variable_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contribution_id: Mapped[int] = mapped_column(
        ForeignKey("contributions.id", ondelete="CASCADE"), index=True
    )
    target_variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"))

    n: Mapped[int] = mapped_column(Integer)
    dtd: Mapped[list] = mapped_column(JSONB)
    dty: Mapped[list] = mapped_column(JSONB)
    yty: Mapped[float] = mapped_column(Float)

    contribution: Mapped[Contribution] = relationship(back_populates="federated_stats")


# --------------------------------------------------------------------------- #
# Model versions and lineage
# --------------------------------------------------------------------------- #
class ModelVersion(Base):
    """A project-level snapshot: "v6".

    The fitted models themselves hang off this, one per (track × target), so a
    two-target project produces four `FittedModel` rows per version while the
    timeline still shows a single entry.
    """

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    n_rows_total: Mapped[int] = mapped_column(Integer, default=0)
    n_contributions: Mapped[int] = mapped_column(Integer, default=0)
    #: Every engine scored on this version's shared rows, plus the suggested
    #: main engine: ``{"targets": {key: [rows]}, "suggestion": {...}}``. See
    #: `api.services.engines.benchmark`.
    benchmark: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="versions")
    fitted_models: Mapped[list[FittedModel]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    sources: Mapped[list[ModelVersionSource]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class ModelVersionSource(Base):
    """Which contributions went into a version — the lineage.

    This is what lets the project page answer "which data made the model
    move?", the question named as the most important one on that page.
    """

    __tablename__ = "model_version_sources"
    __table_args__ = (UniqueConstraint("model_version_id", "contribution_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), index=True
    )
    contribution_id: Mapped[int] = mapped_column(
        ForeignKey("contributions.id", ondelete="CASCADE"), index=True
    )

    version: Mapped[ModelVersion] = relationship(back_populates="sources")
    contribution: Mapped[Contribution] = relationship()


class FittedModel(Base):
    """One fitted model: a (version, track, target) triple."""

    __tablename__ = "fitted_models"
    __table_args__ = (
        UniqueConstraint("version_id", "track", "target_variable_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), index=True
    )
    track: Mapped[ModelTrack] = mapped_column(_enum(ModelTrack, "model_track"))
    target_variable_id: Mapped[int] = mapped_column(ForeignKey("variables.id"))
    engine: Mapped[Engine] = mapped_column(_enum(Engine, "fitted_engine"))
    hyperparams: Mapped[dict | None] = mapped_column(JSONB)

    #: r2_train, rmse, r2_cv, and — the one that justifies the platform —
    #: r2_leave_one_lab_out. See ARCHITECTURE.md §5.6.
    metrics: Mapped[dict | None] = mapped_column(JSONB)

    #: Populated for the linear family only; a GPR has no closed form to show.
    coefficients: Mapped[dict | None] = mapped_column(JSONB)
    scaler: Mapped[dict | None] = mapped_column(JSONB)
    equation: Mapped[str | None] = mapped_column(Text)
    #: On-disk pickle for engines with no serialisable closed form.
    artefact_path: Mapped[str | None] = mapped_column(String(500))

    n_train: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    version: Mapped[ModelVersion] = relationship(back_populates="fitted_models")
    target_variable: Mapped[Variable] = relationship()


# --------------------------------------------------------------------------- #
# Access, jobs, audit
# --------------------------------------------------------------------------- #
class ProjectAccess(Base):
    """Who may do what on a project. The matrix lives in ARCHITECTURE.md §4.1.

    A row is created when a shared contribution is *accepted* — never when it
    is submitted. Model access is the counterpart of data actually admitted to
    the project, and granting it on submission would let anyone unlock a model
    by uploading noise and withdrawing later.
    """

    __tablename__ = "project_access"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[AccessRole] = mapped_column(_enum(AccessRole, "access_role"))
    granted_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    source_contribution_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributions.id", ondelete="SET NULL")
    )

    project: Mapped[Project] = relationship()
    user: Mapped[User] = relationship()


class TrainingJob(Base):
    """A queued or completed training run.

    Training is asynchronous because it has to be: a GPR on a few hundred
    points is quick, but symbolic regression takes minutes, and neither belongs
    in a request cycle.
    """

    __tablename__ = "training_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED, index=True
    )
    kind: Mapped[str] = mapped_column(String(60), default="retrain")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    error: Mapped[str | None] = mapped_column(Text)
    log: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship()


class NotificationKind(str, enum.Enum):
    CONTRIBUTION_SUBMITTED = "contribution_submitted"  # -> project owner
    CONTRIBUTION_ACCEPTED = "contribution_accepted"     # -> contributor
    CONTRIBUTION_REJECTED = "contribution_rejected"     # -> contributor


class Notification(Base):
    """One event surfaced to one user — ROADMAP.md's "most keenly felt gap".

    Without this, an owner learns of a pending contribution only by visiting
    the project page, and a contributor learns of a decision the same way; a
    contribution can sit unseen indefinitely. `title`/`body` are rendered once
    at creation rather than re-derived at read time: a project can be renamed
    after the notification is sent, and the notification should describe the
    event as it happened, not as things stand now.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[NotificationKind] = mapped_column(
        _enum(NotificationKind, "notification_kind"), index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    contribution_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributions.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    project: Mapped[Project | None] = relationship()
    contribution: Mapped[Contribution | None] = relationship()


class AuditLog(Base):
    """Who did what, notably who downloaded which raw file.

    Worth surfacing to contributors rather than keeping internal: it is the
    kind of transparency that builds trust in a platform asking people to hand
    over unpublished measurements, and the kind a data protection review asks
    for.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)


Index("ix_contributions_project_status", Contribution.project_id, Contribution.status)
Index("ix_projects_material_process", Project.material, Project.process)
Index("ix_notifications_recipient_read", Notification.recipient_id, Notification.read_at)
