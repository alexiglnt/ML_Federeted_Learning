"""Pydantic request and response shapes.

Response models are explicit rather than serialising ORM objects directly. That
is not ceremony: an ORM object carries every column it has, including
`password_hash` and the on-disk path of somebody's uploaded file, and the
default for a field nobody thought about should be "not sent".
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from api.models import (
    Engine,
    ProjectStatus,
    ProjectVisibility,
    UserRole,
    VariableKind,
    VariableStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    email: EmailStr
    # Length is the only rule enforced. Composition rules ("one digit, one
    # symbol") push people towards predictable substitutions and are no longer
    # recommended; length is what actually helps.
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=1, max_length=160)
    institution: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    institution: str | None
    country: str | None
    role: UserRole
    created_at: datetime


# --------------------------------------------------------------------------- #
# Variable registry
# --------------------------------------------------------------------------- #
class VariableOut(ORMModel):
    id: int
    key: str
    display_name: str
    symbol: str | None
    unit: str | None
    dimension: str | None
    kind: VariableKind
    categories: list | None
    penalised_sign: float | None
    description: str | None
    status: VariableStatus


class VariableProposal(BaseModel):
    """A quantity a user needs that the registry does not have yet.

    Usable in their project immediately; queued for moderation in parallel.
    Blocking here would turn the registry's completeness into the reason the
    first researcher with an unusual measurement gives up.
    """

    key: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=160)
    symbol: str | None = Field(default=None, max_length=24)
    unit: str | None = Field(default=None, max_length=40)
    dimension: str | None = Field(default=None, max_length=40)
    kind: VariableKind = VariableKind.CONTINUOUS
    penalised_sign: float | None = None
    description: str | None = Field(default=None, max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=20)


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
class ProjectInputSpec(BaseModel):
    variable_key: str
    required: bool = True
    unit: str | None = None
    expected_min: float | None = None
    expected_max: float | None = None
    #: PIML prior for this input *in this project*. Defaults to the registry's
    #: suggestion when omitted. See ProjectInput.penalised_sign for why it is
    #: not simply a property of the variable.
    penalised_sign: float | None = None


class ProjectTargetSpec(BaseModel):
    variable_key: str
    unit: str | None = None


class ProjectCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    material: str | None = Field(default=None, max_length=120)
    process: str | None = Field(default=None, max_length=120)
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC
    main_engine: Engine = Engine.PIML
    accepts_federated: bool = True
    licence: str | None = Field(default=None, max_length=80)
    # Order is part of the contract — permuted inputs give silently wrong
    # coefficients. The position of each entry in this list is stored.
    inputs: list[ProjectInputSpec] = Field(min_length=1, max_length=40)
    targets: list[ProjectTargetSpec] = Field(min_length=1, max_length=10)


class ProjectInputOut(BaseModel):
    variable: VariableOut
    position: int
    required: bool
    unit: str | None
    expected_min: float | None
    expected_max: float | None
    penalised_sign: float | None = None
    #: Actual coverage across all accepted data, which is how the validity
    #: domain bar on the project page shows what contributions added.
    observed_min: float | None = None
    observed_max: float | None = None


class ProjectTargetOut(BaseModel):
    variable: VariableOut
    position: int
    unit: str | None


class ProjectSummary(ORMModel):
    """What a search result card needs, and nothing more."""

    id: int
    slug: str
    title: str
    material: str | None
    process: str | None
    status: ProjectStatus
    main_engine: Engine
    n_rows_total: int = 0
    n_contributors: int = 0
    latest_version: int | None = None
    owner_name: str | None = None


class ProjectDetail(ProjectSummary):
    description: str | None
    visibility: ProjectVisibility
    accepts_federated: bool
    licence: str | None
    created_at: datetime
    inputs: list[ProjectInputOut]
    targets: list[ProjectTargetOut]
    #: What the *viewer* may do, so the front end does not have to re-derive
    #: the permission matrix and get it subtly different from the server.
    viewer_role: str | None = None
    viewer_can_use_model: bool = False
    viewer_can_read_raw_data: bool = False
