/* The single place network calls are made.
 *
 * Kept small and in one file on purpose, a habit inherited from the original
 * site: a researcher deciding whether to hand over unpublished measurements
 * should be able to read what leaves the page in a couple of minutes rather
 * than trust an assurance.
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Pull a readable message out of FastAPI's several error shapes. */
async function errorMessage(response: Response): Promise<string> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return `${response.status} ${response.statusText}`;
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  // A 422 from pydantic is a list of per-field objects, not a string.
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const loc = Array.isArray(item?.loc) ? item.loc.slice(1).join(".") : "";
        return loc ? `${loc}: ${item?.msg}` : String(item?.msg ?? item);
      })
      .join("\n");
  }
  return `${response.status} ${response.statusText}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body && !isForm ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
    // The session lives in an HttpOnly cookie, so it has to be sent along.
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A response meant to be saved rather than rendered.
 *
 * Fetched rather than reached through a plain `<a href>` because both callers —
 * the model export and a raw dataset download — are behind a permission gate,
 * and a refusal delivered as a link opens a tab of raw JSON instead of telling
 * the user what happened. Going through `fetch` keeps the refusal an ApiError
 * like every other one.
 */
async function requestFile(
  path: string,
): Promise<{ blob: Blob; filename: string | null }> {
  const response = await fetch(`/api${path}`, { credentials: "same-origin" });
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? null };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  /** Multipart upload. Content-Type is left unset on purpose: the browser has
   *  to add it itself so that it carries the multipart boundary. */
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form, headers: {} }),
  file: requestFile,
};

/* ----------------------------------------------------------------------- */
/* Shapes mirrored from api/schemas.py                                      */
/* ----------------------------------------------------------------------- */

export type UserRole = "user" | "moderator" | "admin";

export interface User {
  id: number;
  email: string;
  full_name: string;
  institution: string | null;
  country: string | null;
  role: UserRole;
  created_at: string;
}

export interface Variable {
  id: number;
  key: string;
  display_name: string;
  symbol: string | null;
  unit: string | null;
  dimension: string | null;
  kind: "continuous" | "categorical";
  categories: unknown[] | null;
  penalised_sign: number | null;
  description: string | null;
  status: "approved" | "proposed" | "rejected";
}

export type Engine = "linear" | "ridge" | "piml" | "gpr" | "gbm" | "rf";

/** Engines whose loss is quadratic in the coefficients, and which can
 *  therefore be fitted from summed sufficient statistics alone. Only these can
 *  absorb a federated contribution — see ARCHITECTURE.md §5.4. Kept in sync
 *  with `Engine.is_federated_compatible` in api/models.py. */
export const FEDERATED_COMPATIBLE: readonly Engine[] = ["linear", "ridge", "piml"];

export const ENGINE_LABELS: Record<Engine, string> = {
  linear: "Linear regression",
  ridge: "Ridge regression",
  piml: "PIML — linear with physical priors",
  gpr: "Gaussian process regression",
  gbm: "Gradient boosting",
  rf: "Random forest",
};

export interface ProjectSummary {
  id: number;
  slug: string;
  title: string;
  material: string | null;
  process: string | null;
  status: "draft" | "active" | "archived";
  main_engine: Engine;
  n_rows_total: number;
  n_contributors: number;
  latest_version: number | null;
  owner_name: string | null;
}

export interface ProjectInputOut {
  variable: Variable;
  position: number;
  required: boolean;
  unit: string | null;
  expected_min: number | null;
  expected_max: number | null;
  penalised_sign: number | null;
  /** Coverage across every accepted contribution, the owner's included. */
  observed_min: number | null;
  observed_max: number | null;
  /** Coverage from the owner's own data alone. The gap between this pair and
   *  the observed one is exactly what contributors added — which is what the
   *  validity-domain bar draws. */
  owner_min: number | null;
  owner_max: number | null;
}

export interface ProjectTargetOut {
  variable: Variable;
  position: number;
  unit: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  description: string | null;
  visibility: "public" | "unlisted";
  accepts_federated: boolean;
  licence: string | null;
  created_at: string;
  inputs: ProjectInputOut[];
  targets: ProjectTargetOut[];
  viewer_role: string | null;
  viewer_can_use_model: boolean;
  viewer_can_read_raw_data: boolean;
}

export interface ProjectCreatePayload {
  title: string;
  description?: string;
  material?: string;
  process?: string;
  visibility: "public" | "unlisted";
  main_engine: Engine;
  accepts_federated: boolean;
  licence?: string;
  inputs: {
    variable_key: string;
    required: boolean;
    unit?: string | null;
    expected_min?: number | null;
    expected_max?: number | null;
    penalised_sign?: number | null;
  }[];
  targets: { variable_key: string; unit?: string | null }[];
}

export interface HealthReport {
  ok: boolean;
  environment: string;
  database: string;
  front_end_built: boolean;
}

export const auth = {
  me: () => api.get<User | null>("/auth/me"),
  login: (email: string, password: string) =>
    api.post<User>("/auth/login", { email, password }),
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    institution?: string;
    country?: string;
  }) => api.post<User>("/auth/register", payload),
  logout: () => api.post<void>("/auth/logout"),
};

export interface VariableProposalPayload {
  key: string;
  display_name: string;
  symbol?: string;
  unit?: string;
  dimension?: string;
  penalised_sign?: number | null;
  description?: string;
  aliases?: string[];
}

export interface ColumnMatchOut {
  column: string;
  normalised: string;
  matches: {
    variable: Variable;
    confidence: number;
    exact: boolean;
    unit_conflict: string | null;
  }[];
}

export const variables = {
  /** Suggest a registry quantity per column heading.
   *
   *  Used by the federated path, where the file itself never leaves the
   *  machine: only the *headings* are sent. A column name is not a
   *  measurement, and reimplementing the registry matcher in the browser would
   *  guarantee it drifted from the server's. */
  match: (columns: string[]) => {
    const params = new URLSearchParams();
    for (const column of columns) params.append("columns", column);
    return api.get<ColumnMatchOut[]>(`/variables/match?${params}`);
  },
  list: (query?: { q?: string; dimension?: string }) => {
    const params = new URLSearchParams();
    if (query?.q) params.set("q", query.q);
    if (query?.dimension) params.set("dimension", query.dimension);
    const suffix = params.toString() ? `?${params}` : "";
    return api.get<Variable[]>(`/variables${suffix}`);
  },
  propose: (payload: VariableProposalPayload) =>
    api.post<Variable>("/variables", payload),
};

export interface ContributorOut {
  name: string;
  institution: string | null;
  n_rows: number;
  measurement_method: string | null;
  mode: "shared" | "federated";
  contributed_at: string;
}

/** Owner edits. Inputs and targets are absent on purpose — changing them would
 *  invalidate every column mapping already recorded against the project, and
 *  silently. Only their bounds and priors can move. */
export interface ProjectUpdatePayload {
  title?: string;
  description?: string | null;
  material?: string | null;
  process?: string | null;
  visibility?: "public" | "unlisted";
  main_engine?: Engine;
  accepts_federated?: boolean;
  licence?: string | null;
  status?: "draft" | "active" | "archived";
  input_bounds?: Record<
    string,
    { expected_min?: number | null; expected_max?: number | null; penalised_sign?: number | null }
  >;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface FacetVariable {
  key: string;
  display_name: string;
  symbol: string | null;
  unit: string | null;
  count: number;
}

export interface Facets {
  materials: FacetValue[];
  processes: FacetValue[];
  targets: FacetVariable[];
  inputs: FacetVariable[];
}

export interface ProjectFilters {
  q?: string;
  material?: string[];
  process?: string[];
  /** Repeated and required together: a project must declare every one. */
  input?: string[];
  target?: string[];
  min_rows?: number | null;
  has_model?: boolean | null;
  sort?: "recent" | "rows";
}

export interface DetectedColumn {
  variable_key: string;
  column: string;
  confidence: number;
  exact: boolean;
  unit_conflict: string | null;
  n_values: number;
}

export interface ProjectMatch {
  project: ProjectSummary;
  /** Orders the list. A weighted combination, so read the parts below it. */
  score: number;
  inputs_total: number;
  inputs_matched: number;
  inputs_approximate: number;
  matched_inputs: string[];
  missing_inputs: string[];
  missing_required_inputs: string[];
  targets_total: number;
  matched_targets: string[];
  rows_in_domain: number | null;
  rows_scanned: number;
  /** Against the range the project has data for, never the declared one. Null
   *  when the project holds no data yet. */
  fraction_in_domain: number | null;
  unit_conflicts: string[];
}

export interface MatchFileResponse {
  filename: string;
  parse_report: ParseReport;
  detected: DetectedColumn[];
  unmatched_columns: string[];
  matches: ProjectMatch[];
}

function filterParams(filters: ProjectFilters): string {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  for (const value of filters.material ?? []) params.append("material", value);
  for (const value of filters.process ?? []) params.append("process", value);
  for (const value of filters.input ?? []) params.append("input", value);
  for (const value of filters.target ?? []) params.append("target", value);
  if (filters.min_rows) params.set("min_rows", String(filters.min_rows));
  if (filters.has_model !== null && filters.has_model !== undefined) {
    params.set("has_model", String(filters.has_model));
  }
  if (filters.sort && filters.sort !== "recent") params.set("sort", filters.sort);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const projects = {
  list: (q?: string) =>
    api.get<ProjectSummary[]>(`/projects${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  search: (filters: ProjectFilters) =>
    api.get<ProjectSummary[]>(`/projects${filterParams(filters)}`),
  facets: () => api.get<Facets>("/projects/facets"),
  /** Ranks projects against a file. Nothing is stored server-side. */
  match: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<MatchFileResponse>("/projects/match", form);
  },
  mine: () => api.get<ProjectSummary[]>("/projects/mine"),
  get: (slug: string) => api.get<ProjectDetail>(`/projects/${encodeURIComponent(slug)}`),
  create: (payload: ProjectCreatePayload) =>
    api.post<ProjectDetail>("/projects", payload),
  update: (slug: string, payload: ProjectUpdatePayload) =>
    api.patch<ProjectDetail>(`/projects/${encodeURIComponent(slug)}`, payload),
  /** Public: the credit is public, the data is not. */
  contributors: (slug: string) =>
    api.get<ContributorOut[]>(`/projects/${encodeURIComponent(slug)}/contributors`),
};

export interface MappingSuggestion {
  column: string | null;
  confidence: number;
  exact: boolean;
}

export interface ParseReport {
  source: "csv" | "xlsx";
  separator: string | null;
  decimal: string;
  header_row: number;
  sheet: string | null;
  skipped_rows: number;
  n_rows: number;
  n_columns: number;
  notes: string[];
}

export interface UploadPreview {
  upload_token: string;
  filename: string;
  parse_report: ParseReport;
  columns: string[];
  numeric_columns: string[];
  preview_rows: Record<string, string | number | null>[];
  suggested_mapping: Record<string, MappingSuggestion>;
}

export interface ValidationOut {
  ok: boolean;
  n_rows_in_file: number;
  n_rows_usable: number;
  n_rows_dropped: number;
  feature_ranges: Record<string, [number, number]>;
  columns: {
    variable_key: string;
    column: string;
    n_present: number;
    min: number | null;
    max: number | null;
  }[];
  errors: string[];
  warnings: string[];
}

export type ContributionStatus = "pending" | "accepted" | "rejected" | "withdrawn";

/** The published model applied to this contribution's rows as it stands, with
 *  no refitting. Answers "does our model already work on someone else's
 *  bench?". See ARCHITECTURE.md §5.3. */
export interface TransferScore {
  /** The version it was measured against — a score against "the model" means
   *  nothing once the model has moved. Null when there was no model yet. */
  version: number | null;
  per_target: Record<
    string,
    {
      r2?: number | null;
      rmse?: number | null;
      n?: number;
      track?: string;
      engine?: string;
      error?: string;
    }
  >;
  note: string | null;
}

/** A model fitted on this contribution's rows alone, cross-validated. Answers
 *  "are these measurements predictable at all?". */
export interface RefitScore {
  engine: string | null;
  per_target: Record<
    string,
    {
      r2_cv?: number | null;
      rmse_cv?: number | null;
      /** Federated only. Summed statistics cannot be resampled, so there is no
       *  cross-validated figure — this is a training score and says so. */
      r2_train?: number | null;
      rmse_train?: number | null;
      cv_scheme?: string;
      n?: number;
      error?: string;
    }
  >;
  note?: string | null;
}

/** Whether accepting this pending contribution would help or hurt the
 *  model's honest, cross-lab score — checked live against the current
 *  accepted pool, never cached. Shared-mode contributions only: a federated
 *  contribution has no raw rows to hold out and predict. See
 *  ARCHITECTURE.md §5.7. */
export interface PoolabilityScore {
  engine: string | null;
  per_target: Record<
    string,
    {
      /** A model fit on every accepted contributor except this one, scored
       *  against this contribution's own rows: does everyone else's data
       *  predict this lab? */
      own_r2?: number | null;
      own_rmse?: number | null;
      own_n?: number;
      /** Leave-one-lab-out R² of the accepted pool, before vs. after adding
       *  this contribution as one more group. */
      pool_r2_before?: number | null;
      pool_r2_after?: number | null;
      pool_delta?: number | null;
      n_contributors_before?: number | null;
      n_contributors_after?: number | null;
      note?: string;
      error?: string;
    }
  >;
  note?: string | null;
}

export interface ContributionOut {
  id: number;
  project_slug: string;
  contributor_name: string;
  mode: "shared" | "federated";
  status: ContributionStatus;
  n_rows: number;
  measurement_method: string | null;
  notes: string | null;
  feature_ranges: Record<string, [number, number]> | null;
  submitted_at: string;
  original_filename: string | null;
  validation: ValidationOut | null;
  transfer_score: TransferScore | null;
  refit_score: RefitScore | null;
  reviewed_at: string | null;
  review_note: string | null;
}

export interface ReviewResult {
  contribution: ContributionOut;
  access_granted: boolean;
  access_revoked: boolean;
  /** Present only when the decision moved the data a model is fitted on. */
  training_job: TrainingJobOut | null;
}

export const uploads = {
  preview: (slug: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<UploadPreview>(
      `/projects/${encodeURIComponent(slug)}/uploads`,
      form,
    );
  },
  commit: (
    slug: string,
    payload: {
      upload_token: string;
      mapping: Record<string, string>;
      mode?: "shared" | "federated";
      measurement_method?: string;
      notes?: string;
    },
  ) =>
    api.post<ContributionOut>(
      `/projects/${encodeURIComponent(slug)}/datasets`,
      payload,
    ),
  contributions: (slug: string) =>
    api.get<ContributionOut[]>(`/projects/${encodeURIComponent(slug)}/contributions`),
  /** The raw file. Owner, or the contributor themselves. Every call is written
   *  to the audit log below — that is the point of it. */
  download: (slug: string, contributionId: number) =>
    api.file(
      `/projects/${encodeURIComponent(slug)}/contributions/${contributionId}/download`,
    ),
  accessLog: (slug: string) =>
    api.get<AccessLogEntry[]>(`/projects/${encodeURIComponent(slug)}/access-log`),
  /** Owner only, and only for a pending shared contribution. Computed live on
   *  every call — see PoolabilityScore. */
  poolability: (slug: string, contributionId: number) =>
    api.get<PoolabilityScore>(
      `/projects/${encodeURIComponent(slug)}/contributions/${contributionId}/poolability`,
    ),
  /** Owner only. Accepting grants model access and queues a retrain. */
  review: (
    slug: string,
    contributionId: number,
    decision: "accept" | "reject",
    note?: string,
  ) =>
    api.post<ReviewResult>(
      `/projects/${encodeURIComponent(slug)}/contributions/${contributionId}/review`,
      { decision, note: note || undefined },
    ),
  /** The contributor's own decision, and it surrenders model access with the
   *  data — the owner cannot do this on their behalf. */
  withdraw: (slug: string, contributionId: number) =>
    api.post<ReviewResult>(
      `/projects/${encodeURIComponent(slug)}/contributions/${contributionId}/withdraw`,
    ),
  /** Contribute without transmitting any measurement.
   *
   *  The payload carries only the sums computed in `lib/federated.ts`, plus the
   *  ranges of each input and the column names the user confirmed. No row of
   *  the file reaches this function. */
  federated: (
    slug: string,
    payload: {
      stats: Record<string, { n: number; dtd: number[][]; dty: number[]; yty: number }>;
      feature_ranges: Record<string, [number, number]>;
      column_mapping?: Record<string, string>;
      measurement_method?: string;
      notes?: string;
    },
  ) =>
    api.post<ContributionOut>(
      `/projects/${encodeURIComponent(slug)}/federated`,
      payload,
    ),
  /** Turn an existing federated contribution into a shared one, in place.
   *
   *  ⚠️ Never a second contribution — see ARCHITECTURE.md §5.5. The server
   *  drops the summary statistics as it attaches the file, so the data cannot
   *  be counted twice. */
  share: (
    slug: string,
    contributionId: number,
    payload: {
      upload_token: string;
      mapping: Record<string, string>;
      measurement_method?: string;
      notes?: string;
    },
  ) =>
    api.post<ReviewResult>(
      `/projects/${encodeURIComponent(slug)}/contributions/${contributionId}/share`,
      payload,
    ),
};

export interface AccessLogEntry {
  at: string;
  actor_name: string;
  action: string;
  detail: { project?: string; filename?: string; by_owner?: boolean } | null;
}

export interface FittedModelOut {
  track: "reference" | "main";
  target_key: string;
  target_name: string;
  target_unit: string | null;
  engine: Engine;
  n_train: number;
  metrics: {
    r2_train?: number | null;
    rmse_train?: number | null;
    r2_cv?: number | null;
    rmse_cv?: number | null;
    cv_scheme?: string;
    r2_leave_one_lab_out?: number | null;
    n_sources?: number;
    n_train?: number;
    cv_note?: string;
    n_federated_sources?: number;
  };
  hyperparams: Record<string, unknown>;
  /** Null unless the viewer has earned model access. */
  coefficients: { intercept: number; coef: Record<string, number> } | null;
  scaler: { mean: number[]; std: number[] } | null;
  equation: string | null;
  opaque: boolean;
}

export interface VersionSourceOut {
  contribution_id: number;
  contributor_name: string;
  n_rows: number;
  measurement_method: string | null;
  mode: "shared" | "federated";
}

export interface ModelVersionOut {
  number: number;
  created_at: string;
  note: string | null;
  n_rows_total: number;
  n_contributions: number;
  headline_r2: number | null;
  models: FittedModelOut[];
  sources: VersionSourceOut[];
}

export interface TrainingJobOut {
  id: number;
  status: "queued" | "running" | "done" | "failed";
  kind: string;
  error: string | null;
  log: string | null;
}

export type ModelTrack = "reference" | "main";

export interface PredictRequestPayload {
  /** {variable_key: value}, one per project input. */
  values: Record<string, number>;
  version?: number | null;
  track?: ModelTrack;
}

export interface PredictionOut {
  target_key: string;
  target_name: string;
  target_unit: string | null;
  value: number;
  engine: Engine;
  track: ModelTrack;
}

export interface PredictResponse {
  version: number;
  predictions: PredictionOut[];
  /** One sentence per input that sits outside the range the model has data
   *  for. Extrapolation is answered, not refused — but it is a different kind
   *  of claim and the caller is told so. */
  out_of_domain: string[];
}

export const modelsApi = {
  versions: (slug: string) =>
    api.get<ModelVersionOut[]>(`/projects/${encodeURIComponent(slug)}/versions`),
  latest: (slug: string) =>
    api.get<ModelVersionOut>(`/projects/${encodeURIComponent(slug)}/model`),
  train: (slug: string) =>
    api.post<TrainingJobOut>(`/projects/${encodeURIComponent(slug)}/train`),
  job: (slug: string, id: number) =>
    api.get<TrainingJobOut>(`/projects/${encodeURIComponent(slug)}/jobs/${id}`),
  predict: (slug: string, payload: PredictRequestPayload) =>
    api.post<PredictResponse>(`/projects/${encodeURIComponent(slug)}/predict`, payload),
  /** The citable JSON document: units, metrics, and the exact contributions
   *  behind the fit. Same gate as the coefficients. */
  export: (slug: string, version?: number | null) =>
    api.file(
      `/projects/${encodeURIComponent(slug)}/export${version ? `?version=${version}` : ""}`,
    ),
};

export const health = () => api.get<HealthReport>("/health");
