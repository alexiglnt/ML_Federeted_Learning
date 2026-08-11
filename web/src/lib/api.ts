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
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
    // The session lives in an HttpOnly cookie, so it has to be sent along.
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
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

export const variables = {
  list: (query?: { q?: string; dimension?: string }) => {
    const params = new URLSearchParams();
    if (query?.q) params.set("q", query.q);
    if (query?.dimension) params.set("dimension", query.dimension);
    const suffix = params.toString() ? `?${params}` : "";
    return api.get<Variable[]>(`/variables${suffix}`);
  },
};

export const health = () => api.get<HealthReport>("/health");
