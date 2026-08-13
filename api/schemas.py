"""Pydantic request and response shapes.

Response models are explicit rather than serialising ORM objects directly. That
is not ceremony: an ORM object carries every column it has, including
`password_hash` and the on-disk path of somebody's uploaded file, and the
default for a field nobody thought about should be "not sent".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from api.models import (
    ContributionMode,
    ContributionStatus,
    Engine,
    JobStatus,
    ModelTrack,
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
    #: Coverage across all accepted data.
    observed_min: float | None = None
    observed_max: float | None = None
    #: Coverage from the owner's own data alone. The gap between this and the
    #: observed range is precisely what contributors added, which is what the
    #: validity-domain bar on the project page draws.
    owner_min: float | None = None
    owner_max: float | None = None


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


# --------------------------------------------------------------------------- #
# Uploads and datasets
# --------------------------------------------------------------------------- #
class MappingSuggestion(BaseModel):
    column: str | None
    confidence: float
    exact: bool


class UploadPreview(BaseModel):
    """What comes back from step one of an upload, before anything is kept.

    The file is parsed and set aside; nothing is recorded against the project
    until the mapping is confirmed. `upload_token` is the signed claim ticket
    for the staged file.
    """

    upload_token: str
    filename: str
    parse_report: dict
    columns: list[str]
    numeric_columns: list[str]
    #: First few rows, so the uploader can see the file was read as intended —
    #: a wrong decimal mark or header row is obvious in a preview and invisible
    #: in a summary.
    preview_rows: list[dict]
    #: {variable_key: suggestion} for every input and target of the project.
    suggested_mapping: dict[str, MappingSuggestion]


class DatasetCommit(BaseModel):
    upload_token: str
    #: {variable_key: column name}. Confirmed by the user, never inferred
    #: silently — a wrong column fits the model to the wrong thing.
    mapping: dict[str, str]
    mode: ContributionMode = ContributionMode.SHARED
    measurement_method: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=4000)


class ValidationOut(BaseModel):
    ok: bool
    n_rows_in_file: int
    n_rows_usable: int
    n_rows_dropped: int
    feature_ranges: dict[str, list[float]] = {}
    columns: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []


class ContributionOut(BaseModel):
    id: int
    project_slug: str
    contributor_name: str
    mode: ContributionMode
    status: ContributionStatus
    n_rows: int
    measurement_method: str | None
    notes: str | None
    feature_ranges: dict | None
    submitted_at: datetime
    #: Present for the owner and for the contributor themselves; the filename
    #: is a small thing but it is still someone else's business.
    original_filename: str | None = None
    validation: ValidationOut | None = None
    #: The two scores of ARCHITECTURE.md §5.3. Shown to the owner, who reviews
    #: on them, and to the contributor about their own data — a contributor who
    #: is told their measurements scored badly can go and look at them.
    transfer_score: dict | None = None
    refit_score: dict | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class PoolabilityOut(BaseModel):
    """The third score of ARCHITECTURE.md §5.7, checked on request.

    Unlike `transfer_score`/`refit_score`, this is never stored on the
    `Contribution` row — it is a question about the *current* accepted pool,
    which shifts under a pending contribution every time another one is
    accepted or rejected, so a cached answer would go stale silently.
    """

    engine: str | None = None
    #: {target_key: {own_r2, own_rmse, own_n, pool_r2_before, pool_r2_after,
    #: pool_delta, n_contributors_before, n_contributors_after}} on success,
    #: or {target_key: {"note"/"error": str}} when nothing was computable.
    per_target: dict = {}
    note: str | None = None


class ContributionReview(BaseModel):
    """An owner's decision on one contribution.

    Review exists because "share data → get the model" is otherwise an open
    invitation to upload noise in order to unlock a model (ARCHITECTURE.md
    §4.2). It is the only thing standing between the incentive and the abuse of
    it.
    """

    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=4000)


class SufficientStatisticsIn(BaseModel):
    """One target's summary, as computed in the contributor's browser.

    ``D'D``, ``D'y``, ``y'y`` and ``n`` with ``D = [1, X]`` and the inputs in
    the project's declared order. That order is contractual: a permuted design
    matrix fits silently wrong coefficients, and here there is no file to
    re-read afterwards to notice.
    """

    n: int = Field(ge=1)
    dtd: list[list[float]]
    dty: list[float]
    yty: float


class FederatedCommit(BaseModel):
    """A contribution made without transmitting any measurement.

    The counterpart of `DatasetCommit`. What arrives is the summary above, per
    target, plus the ranges of the inputs — which is what grows the published
    validity domain and is the only description of the data the project ever
    gets.
    """

    #: {target_variable_key: summary}
    stats: dict[str, SufficientStatisticsIn] = Field(min_length=1)
    #: {input_variable_key: [min, max]}, over the rows behind the summary.
    feature_ranges: dict[str, list[float]] = Field(default_factory=dict)
    #: Echoed back so the interface can show what the browser matched. The
    #: column *names* leave the machine; the measurements never do.
    column_mapping: dict[str, str] = Field(default_factory=dict)
    measurement_method: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=4000)


class ContributorOut(BaseModel):
    """Public credit for a contribution.

    Public on purpose: this is the scientific credit for handing over
    measurements that cost machine time to produce, and it is most of what a
    contributor gets in return besides model access. What stays private is the
    file itself, not the fact of having contributed.
    """

    name: str
    institution: str | None
    n_rows: int
    measurement_method: str | None
    mode: ContributionMode
    contributed_at: datetime


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
class FacetValue(BaseModel):
    value: str
    count: int


class FacetVariable(BaseModel):
    key: str
    display_name: str
    symbol: str | None
    unit: str | None
    count: int


class FacetsOut(BaseModel):
    """The filter values that exist, with counts.

    Derived from the data rather than hardcoded: a facet that offers a choice
    returning nothing reads as a broken search.
    """

    materials: list[FacetValue] = []
    processes: list[FacetValue] = []
    targets: list[FacetVariable] = []
    inputs: list[FacetVariable] = []


class DetectedColumnOut(BaseModel):
    """One column of an uploaded file, and the quantity it appears to be."""

    variable_key: str
    column: str
    confidence: float
    exact: bool
    #: The strongest available signal that a name match is wrong.
    unit_conflict: str | None = None
    n_values: int


class ProjectMatchOut(BaseModel):
    """How well one project fits an uploaded file.

    Every part is reported rather than reduced to a verdict. `score` exists to
    order the list; it is a weighted combination and therefore a judgement,
    which is why the parts sit beside it and the interface shows them.
    """

    project: ProjectSummary
    score: float
    inputs_total: int
    inputs_matched: int
    #: Matched on a similar name rather than an exact one. Always worth a look:
    #: a column matched to the wrong quantity fits the model to the wrong thing.
    inputs_approximate: int
    matched_inputs: list[str] = []
    missing_inputs: list[str] = []
    #: Without these the file cannot be contributed as it stands.
    missing_required_inputs: list[str] = []
    targets_total: int
    matched_targets: list[str] = []
    #: Rows falling inside the range the project has **data** for, on every
    #: matched input at once. Null when the project holds no data yet. A low
    #: fraction is not a warning — it marks data that would extend the domain.
    rows_in_domain: int | None = None
    rows_scanned: int = 0
    fraction_in_domain: float | None = None
    unit_conflicts: list[str] = []


class MatchFileResponse(BaseModel):
    filename: str
    parse_report: dict
    detected: list[DetectedColumnOut] = []
    #: Columns no registry quantity claimed. Worth showing: a heading nobody
    #: recognises is how a user discovers the registry is missing a quantity.
    unmatched_columns: list[str] = []
    matches: list[ProjectMatchOut] = []


class ProjectUpdate(BaseModel):
    """Owner edits. Every field optional; only what is sent is changed.

    Inputs and targets are deliberately absent. Changing them after data has
    arrived would invalidate every mapping already recorded against the
    project, and silently so — the fix is to create a new project, not to
    mutate this one.
    """

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    material: str | None = Field(default=None, max_length=120)
    process: str | None = Field(default=None, max_length=120)
    visibility: ProjectVisibility | None = None
    main_engine: Engine | None = None
    accepts_federated: bool | None = None
    licence: str | None = Field(default=None, max_length=80)
    status: ProjectStatus | None = None
    #: {variable_key: {expected_min, expected_max, penalised_sign}}
    input_bounds: dict[str, dict[str, float | None]] | None = None


class PredictRequest(BaseModel):
    #: {variable_key: value}, one per project input.
    values: dict[str, float]
    version: int | None = None
    track: ModelTrack = ModelTrack.MAIN


class PredictionOut(BaseModel):
    target_key: str
    target_name: str
    target_unit: str | None
    value: float
    engine: Engine
    track: ModelTrack


class PredictResponse(BaseModel):
    version: int
    predictions: list[PredictionOut]
    #: Raised when an input sits outside the range the model actually has data
    #: for. Extrapolation is not refused — a model is still the best guess
    #: available — but a prediction outside the covered domain is a different
    #: kind of claim and the caller has to be told.
    out_of_domain: list[str] = []


class AccessLogEntry(BaseModel):
    """Who read what, shown to the people whose data was read."""

    at: datetime
    actor_name: str
    action: str
    detail: dict | None = None


# --------------------------------------------------------------------------- #
# Models and versions
# --------------------------------------------------------------------------- #
class FittedModelOut(BaseModel):
    """One fitted model.

    Metrics are public; coefficients and the equation are not. That split is
    the incentive the platform runs on — a visitor can see that a project's
    model is worth having before deciding to contribute, without being handed
    it. `coefficients`, `scaler` and `equation` are filled only for viewers who
    may use the model.
    """

    track: ModelTrack
    target_key: str
    target_name: str
    target_unit: str | None
    engine: Engine
    n_train: int
    metrics: dict = {}
    hyperparams: dict = {}
    coefficients: dict | None = None
    scaler: dict | None = None
    equation: str | None = None
    #: True when this engine has no closed form to publish, only a stored
    #: estimator — so the interface offers prediction rather than an equation.
    opaque: bool = False


class VersionSourceOut(BaseModel):
    contribution_id: int
    contributor_name: str
    n_rows: int
    measurement_method: str | None
    mode: ContributionMode


class ModelVersionOut(BaseModel):
    number: int
    created_at: datetime
    note: str | None
    n_rows_total: int
    n_contributions: int
    #: Headline score: leave-one-lab-out where available, cross-validated R²
    #: otherwise. Never training R².
    headline_r2: float | None = None
    models: list[FittedModelOut] = []
    #: The lineage — which data made this version. This is what the version
    #: timeline is for.
    sources: list[VersionSourceOut] = []


class TrainingJobOut(BaseModel):
    id: int
    status: JobStatus
    kind: str
    error: str | None = None
    log: str | None = None


class ReviewResult(BaseModel):
    """What a review decision actually changed, so the interface need not guess.

    `training_job` is present only when the decision moved the data a model is
    fitted on — accepting anything, or rejecting or withdrawing something that
    had already been accepted. Rejecting a contribution that was merely pending
    changes no model and queues nothing, because pending data was never in one.
    """

    contribution: ContributionOut
    access_granted: bool = False
    access_revoked: bool = False
    training_job: TrainingJobOut | None = None


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
