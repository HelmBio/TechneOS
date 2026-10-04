/**
 * API client for TechneOS.
 *
 * Wraps fetch() with auth header injection, error handling, typed responses,
 * and automatic token refresh on 401.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`HTTP ${status}: ${detail}`);
  }
}

/** Shown when an SSO sign-in is refused because the account awaits approval. */
export const PENDING_APPROVAL_MESSAGE =
  "Your account has been created and is awaiting administrator approval. " +
  "You can sign in once an admin activates it.";

/** User-facing message for a failed SSO token exchange. */
export function ssoErrorMessage(err: unknown): string {
  // The auth service answers 403 when the account exists but is inactive.
  if (err instanceof ApiError && err.status === 403) {
    return PENDING_APPROVAL_MESSAGE;
  }
  return err instanceof Error ? err.message : "SSO login failed";
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("techneos_access_token");
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("techneos_refresh_token");
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem("techneos_access_token", access);
  localStorage.setItem("techneos_refresh_token", refresh);
}

export function clearTokens() {
  localStorage.removeItem("techneos_access_token");
  localStorage.removeItem("techneos_refresh_token");
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

/**
 * Decode the JWT payload (without verification) to read claims like `role`.
 * Returns null if no token or decoding fails.
 */
export function getTokenClaims(): {
  sub: string;
  email: string;
  role: string | null;
  org_id: string | null;
  team_id: string | null;
  permissions: string[];
  exp: number | null;
} | null {
  const token = getToken();
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(
      atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")),
    );
    return {
      sub: payload.sub ?? "",
      email: payload.email ?? "",
      role: payload.role ?? null,
      org_id: payload.org_id ?? null,
      team_id: payload.team_id ?? null,
      permissions: payload.permissions ?? [],
      exp: payload.exp ?? null,
    };
  } catch {
    return null;
  }
}

// ── Token refresh ──────────────────────────────────────────

let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  try {
    const resp = await fetch(
      `${API_BASE}/api/v1/auth/refresh?refresh_token=${encodeURIComponent(refresh)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      },
    );
    if (!resp.ok) return false;
    const body = await resp.json();
    setTokens(body.access_token, body.refresh_token);
    // Notify pages so they can re-fetch with the new token immediately
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("token-refreshed"));
    }
    return true;
  } catch {
    return false;
  }
}

/** Attempt to refresh the token, deduplicating concurrent calls. */
export function refreshTokenOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = tryRefreshToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

// ── Session expiry event ───────────────────────────────────

/** Emit when auth fails and refresh is not possible. UI listens to show alert. */
let _sessionExpiredFlag = false;

export function emitSessionExpired() {
  _sessionExpiredFlag = true;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("session-expired"));
  }
}

/** Check (and clear) whether a session-expired event was emitted before listeners mounted. */
export function consumeSessionExpiredFlag(): boolean {
  const v = _sessionExpiredFlag;
  _sessionExpiredFlag = false;
  return v;
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

// ── Response handling ──────────────────────────────────────

async function handleResponse<T>(resp: Response): Promise<T> {
  if (resp.status === 204) return undefined as T;
  if (!resp.ok) {
    // If the response is 401/403 after fetchWithRetry exhausted its retries,
    // the session-expired modal is already being shown.  Throw a distinct
    // error so callers can silently ignore it instead of surfacing a noisy
    // console error / Next.js overlay.
    if (resp.status === 401) {
      // Only treat as session expiry if the user already had a token.
      // During login there is no token, so 401 means invalid credentials.
      if (getToken()) {
        throw new SessionExpiredError();
      }
      let detail = "Invalid email or password";
      try {
        const body = await resp.json();
        if (body.detail) detail = body.detail;
      } catch {
        /* ignore */
      }
      throw new ApiError(401, detail);
    }
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore parse errors */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
}

function headers(): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

/** Perform a fetch, retrying with the latest token if the supplied one is stale. */
export async function fetchWithRetry(
  input: string,
  init?: RequestInit,
): Promise<Response> {
  // credentials: 'include' so the platform's HTTP-only session cookie is sent
  // and Set-Cookie responses are honored on cross-origin requests to the gateway.
  const baseInit: RequestInit = { credentials: "include", ...init };
  const attemptWithCurrentToken = () => {
    const h = {
      ...Object.fromEntries(new Headers(baseInit.headers).entries()),
    };
    const token = getToken();
    if (token) h["Authorization"] = `Bearer ${token}`;
    return fetch(input, { ...baseInit, headers: h });
  };

  // If the token in the supplied headers is already stale (a refresh happened
  // since the caller built them), skip the doomed first request entirely and
  // go straight with the current token.
  const suppliedToken = new Headers(baseInit.headers).get("Authorization");
  const currentToken = getToken();
  const tokenAlreadyStale =
    suppliedToken && currentToken && suppliedToken !== `Bearer ${currentToken}`;

  let resp = tokenAlreadyStale
    ? await attemptWithCurrentToken()
    : await fetch(input, baseInit);

  // If we got 401 and the token in localStorage has changed since we sent the
  // request (another caller refreshed it), retry once with the latest token.
  // We intentionally do NOT call refreshTokenOnce() here — token refresh is
  // managed exclusively by the proactive check timer in AuthProvider, which
  // respects the user-activity threshold.
  if (resp.status === 401) {
    const latestToken = getToken();
    if (latestToken && latestToken !== currentToken) {
      resp = await attemptWithCurrentToken();
    }
  }
  return resp;
}

/**
 * POST to an SSE endpoint with auth and automatic 401/403 → refresh → retry.
 * Returns the raw Response so callers can read the stream.
 */
export async function ssePost(path: string, body: unknown): Promise<Response> {
  const url = `${API_BASE}${path}`;
  const buildInit = (): RequestInit => ({
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify(body),
  });

  return fetchWithRetry(url, buildInit());
}

export async function apiGet<T = unknown>(
  path: string,
  params?: Record<string, string>,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params)
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const resp = await fetchWithRetry(url.toString(), { headers: headers() });
  return handleResponse<T>(resp);
}

export async function apiPost<T = unknown>(
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method: "POST",
    headers: headers(),
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const resp = await fetchWithRetry(`${API_BASE}${path}`, init);
  return handleResponse<T>(resp);
}

export async function apiPut<T = unknown>(
  path: string,
  body?: unknown,
): Promise<T> {
  const resp = await fetchWithRetry(`${API_BASE}${path}`, {
    method: "PUT",
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(resp);
}

export async function apiPatch<T = unknown>(
  path: string,
  body?: unknown,
): Promise<T> {
  const resp = await fetchWithRetry(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(resp);
}

export async function apiDelete(path: string): Promise<void> {
  const resp = await fetchWithRetry(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: headers(),
  });
  return handleResponse<void>(resp);
}

export interface TaskInputUploadResponse {
  input_id: string;
  storage_path: string;
  compounds_count: number | null;
  file_size: number;
}

export async function apiUploadTaskInput(
  toolSlug: string,
  toolVersionId: string,
  file: File,
): Promise<TaskInputUploadResponse> {
  const formData = new FormData();
  formData.append("tool_slug", toolSlug);
  formData.append("tool_version_id", toolVersionId);
  formData.append("file", file);

  const token = getToken();
  const resp = await fetchWithRetry(
    `${API_BASE}/api/v1/task-runs/from-tool/upload`,
    {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    },
  );
  return handleResponse<TaskInputUploadResponse>(resp);
}

export interface TaskOutputUploadResponse {
  storage_path: string;
  file_name: string;
  content_type: string;
  file_size: number;
}

export async function apiUploadTaskOutput(
  taskRunId: string,
  file: File,
): Promise<TaskOutputUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const token = getToken();
  const resp = await fetchWithRetry(
    `${API_BASE}/api/v1/task-runs/${taskRunId}/upload-output`,
    {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    },
  );
  return handleResponse<TaskOutputUploadResponse>(resp);
}

// ── OIDC / PKCE helpers ────────────────────────────────────

export interface KeycloakConfig {
  authorization_endpoint: string;
  token_endpoint: string;
  userinfo_endpoint: string;
  end_session_endpoint: string;
  client_id: string;
}

export interface OAuth2Config {
  authorization_endpoint: string;
  token_endpoint: string;
  client_id: string;
  redirect_uri: string;
  scopes: string;
}

export interface OIDCConfig {
  local: boolean; // email/password always available
  keycloak: KeycloakConfig | null; // present when Keycloak is configured
  oauth2: OAuth2Config | null; // present when OAuth2 (SSO) is configured
}

let oidcConfigCache: OIDCConfig | null = null;

export async function getOIDCConfig(): Promise<OIDCConfig> {
  if (oidcConfigCache) return oidcConfigCache;
  const resp = await fetch(`${API_BASE}/api/v1/auth/oidc/config`);
  oidcConfigCache = await resp.json();
  return oidcConfigCache!;
}

function base64urlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

export async function generatePKCE(): Promise<{
  codeVerifier: string;
  codeChallenge: string;
}> {
  if (typeof crypto.subtle?.digest !== "function") {
    throw new Error(
      "Social login requires a secure connection (HTTPS). " +
        "Use email/password or access the platform via HTTPS.",
    );
  }
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  const codeVerifier = base64urlEncode(array.buffer);
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(codeVerifier),
  );
  const codeChallenge = base64urlEncode(digest);
  return { codeVerifier, codeChallenge };
}

/**
 * Build the Keycloak authorization URL.
 *
 * Pass `idpHint` (e.g. "google", "github") to skip the Keycloak login page
 * and redirect directly to that identity provider via `kc_idp_hint`.
 */
export function buildKeycloakLoginUrl(
  config: KeycloakConfig,
  codeChallenge: string,
  redirectUri: string,
  state: string,
  idpHint?: string,
): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: redirectUri,
    scope: "openid profile email",
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    state,
  });
  if (idpHint) {
    params.set("kc_idp_hint", idpHint);
  }
  return `${config.authorization_endpoint}?${params.toString()}`;
}

/**
 * Build a generic OAuth2 authorization URL (e.g. PingFederate).
 *
 * Unlike the Keycloak builder, this uses the redirect_uri from the server
 * config (which must match what is registered with the enterprise IdP).
 */
export function buildOAuth2LoginUrl(
  config: OAuth2Config,
  state: string,
): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: config.redirect_uri,
    state,
  });
  if (config.scopes) {
    params.set("scope", config.scopes);
  }
  return `${config.authorization_endpoint}?${params.toString()}`;
}

// ── Types ──────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  org_id: string | null;
  team_id: string | null;
  role_id: string | null;
  auth_method: string;
  permissions: string[];
  created_at: string;
  updated_at: string;
}

export interface Dataset {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  data_type: string;
  file_format: string | null;
  tags: string[];
  data_schema: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  is_public: boolean;
  org_id: string;
  created_by: string;
  creator_name: string | null;
  updated_by: string | null;
  updated_by_name: string | null;
  org_name: string | null;
  version_count: number;
  latest_version: number | null;
  latest_version_status: string | null;
  total_size: number;
  total_file_count: number;
  created_at: string;
  updated_at: string;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  version: number;
  description: string | null;
  status: string;
  created_by: string;
  creator_name: string | null;
  updated_by: string | null;
  updated_by_name: string | null;
  storage_bucket: string;
  files: {
    file_name: string;
    file_size: number;
    content_type: string;
    storage_key: string;
    checksum_sha256: string | null;
  }[];
  transfer_method: string | null;
  source_bucket_id: string | null;
  source_files: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface DatasetWithVersions extends Dataset {
  versions: DatasetVersion[];
}

export interface Tool {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  category: string;
  tool_type: string;
  tags: string[];
  is_public: boolean;
  // README is tool-level (moved from tool_versions). repository_url was
  // dropped — per-version provenance lives in ToolVersion.git_ref.
  readme: string | null;
  org_id: string;
  created_by: string;
  creator_name: string | null;
  updated_by: string | null;
  updated_by_name: string | null;
  org_name: string | null;
  version_count: number;
  latest_version: number | null;
  latest_version_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface ToolVersion {
  id: string;
  tool_id: string;
  version: number;
  docker_image: string | null;
  docker_tag: string | null;
  package_name: string | null;
  package_version: string | null;
  entry_point: string | null;
  package_index_url: string | null;
  // Human tool config fields
  assignment_type: string | null;
  default_assignee: string | null;
  default_project_lead_email: string | null;
  instructions_template: string | null;
  due_in_hours: number | null;
  require_attachments: boolean;
  priority: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  parameters_schema: Record<string, unknown>;
  resource_requirements: Record<string, unknown>;
  changelog: string | null;
  status: string;
  created_by: string;
  creator_name: string | null;
  updated_by: string | null;
  updated_by_name: string | null;
  // True when any run references this version, freezing its definition.
  has_runs?: boolean;
  created_at: string;
  updated_at: string;
}

export interface ToolWithVersions extends Tool {
  versions: ToolVersion[];
}

export interface ComputeBackend {
  id: string;
  name: string;
  display_name: string;
  backend_type: string;
  description: string | null;
  status: string;
  config: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ComputeArtifact {
  id: string;
  kind: string; // "wheel" | "docker_image"
  origin: string; // catalog | platform | other
  name: string;
  version: string;
  registry_url: string | null;
  digest: string | null;
  size_bytes: number | null;
  source_commit_sha: string | null;
  source_repo: string | null;
  status: string; // available | deprecated | deleted
  metadata: Record<string, unknown>;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Subscription {
  id: string;
  user_id: string;
  resource_type: string;
  resource_id: string;
  preferences: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionCheck {
  subscribed: boolean;
  subscription_id: string | null;
}

export interface Notification {
  id: string;
  user_id: string;
  title: string;
  message: string;
  link: string | null;
  category: string;
  is_read: boolean;
  source_type: string | null;
  source_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Pipeline {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  readme: string | null;
  category: string;
  pipeline_type: string;
  version: number;
  tags: string[];
  is_public: boolean;
  // Canonical DAG shape — the pipeline owns the graph; versions
  // only pin tools/params. Steps are shape-only (no tool_version/parameters).
  steps: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  parameters_schema: Record<string, unknown>;
  topology_hash: string | null;
  forked_from: string | null;
  org_id: string;
  created_by: string;
  updated_by: string | null;
  org_name: string | null;
  created_by_email: string | null;
  creator_name: string | null;
  updated_by_name: string | null;
  run_count: number;
  last_run_status: string | null;
  version_count: number;
  latest_version: number | null;
  latest_version_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface PipelineVersion {
  id: string;
  pipeline_id: string;
  version: number;
  // Per-version binding: { step_name -> { tool_version, parameters } }.
  bindings: Record<string, { tool_version: number | null; parameters: Record<string, unknown> }>;
  // Effective DAG (parent shape merged with this version's bindings), computed
  // server-side for backward compatibility (run dialog / legacy consumers).
  steps: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  parameters_schema: Record<string, unknown>;
  status: string;
  changelog: string | null;
  created_by: string;
  updated_by: string | null;
  creator_name: string | null;
  updated_by_name: string | null;
  // True when any run references this version, freezing its definition.
  has_runs?: boolean;
  created_at: string;
  updated_at: string;
}

export interface PipelineWithVersions extends Pipeline {
  versions: PipelineVersion[];
}

export interface PipelineStepConfig {
  name: string;
  tool_slug: string;
  tool_version: number | null;
  tool_type?: string;
  parameters: Record<string, unknown>;
  depends_on: string[];
  // Pipeline pinning: omit tool_version to pin at save time, or
  // set track_latest=true to resolve "latest active" at dispatch instead.
  track_latest?: boolean;
}

export interface PipelineEdge {
  from_step: string;
  to_step: string;
}

export interface PipelineRun {
  id: string;
  version_id: string;
  pipeline_id: string | null;
  name: string | null;
  status: string;
  parameters: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  airflow_dag_id: string | null;
  airflow_run_id: string | null;
  org_id: string;
  submitted_by: string;
  restarted_from: string | null;
  pipeline_name: string | null;
  pipeline_slug: string | null;
  pipeline_version: number | null;
  submitted_by_email: string | null;
  org_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface StepRun {
  id: string;
  run_id: string;
  step_name: string;
  tool_version_id: string | null;
  status: string;
  parameters: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: string;
  run_id: string;
  step_name: string | null;
  name: string;
  artifact_type: string;
  file_name: string;
  file_size: number;
  content_type: string;
  checksum_sha256: string | null;
  created_at: string;
  updated_at: string;
}

export interface PipelineRunDetail extends PipelineRun {
  steps: StepRun[];
  artifacts: Artifact[];
}

export interface ArtifactDownload {
  artifact_id: string;
  download_url: string;
  expires_in_seconds: number;
}

// ── Tool runs ──────────────────────────────────────────────

export interface ToolRun {
  id: string;
  tool_version_id: string;
  status: string;
  parameters: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  airflow_dag_id: string | null;
  airflow_run_id: string | null;
  log_storage_key: string | null;
  org_id: string;
  submitted_by: string;
  restarted_from: string | null;
  tool_id: string | null;
  tool_slug: string | null;
  tool_name: string | null;
  tool_version_num: number | null;
  submitted_by_email: string | null;
  org_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface ToolRunArtifact {
  id: string;
  tool_run_id: string;
  io_type: string;
  file_name: string;
  file_size: number;
  content_type: string;
  checksum_sha256: string | null;
  storage_bucket: string | null;
  storage_key: string | null;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ToolRunDetail extends ToolRun {
  artifacts: ToolRunArtifact[];
}

// ── Admin types ────────────────────────────────────────────

export interface AdminStats {
  total_users: number;
  active_users: number;
  total_orgs: number;
  active_orgs: number;
  total_teams: number;
  total_roles: number;
  total_llm_providers: number;
  default_llm_providers: number;
  total_buckets: number;
  default_buckets: number;
  total_compute_backends: number;
  enabled_compute_backends: number;
  total_artifacts: number;
}

export interface ServiceHealth {
  name: string;
  url: string;
  status: "healthy" | "unhealthy" | "unreachable";
  latency_ms: number | null;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
  is_active: boolean;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Team {
  id: string;
  name: string;
  org_id: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string | null;
  timestamp: string;
}

export interface AdminUserUpdatePayload {
  full_name?: string;
  email?: string;
  is_active?: boolean;
  org_id?: string | null;
  team_id?: string | null;
  role_name?: string | null;
}

export interface DockerContainer {
  id: string;
  name: string;
  image: string;
  status: string;
  health: string | null;
  state: string;
  created: string;
  ports: string[];
}

export interface DockerContainerLogs {
  container_id: string;
  container_name: string;
  logs: string;
}

export interface ServiceLogs {
  service_name: string;
  logs: string;
}

export interface LLMProvider {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  provider_type: string;
  base_url: string | null;
  has_api_key: boolean;
  default_model: string;
  supported_models: string[];
  max_tokens: number | null;
  is_default: boolean;
  is_active: boolean;
  org_id: string;
  org_name: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ObjectStoreBucket {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  bucket_name: string;
  endpoint_url: string | null;
  region: string | null;
  secure: boolean;
  has_access_key: boolean;
  has_secret_key: boolean;
  is_default: boolean;
  is_active: boolean;
  org_id: string;
  org_name: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ObjectInfo {
  bucket: string;
  key: string;
  size: number;
  content_type: string | null;
  metadata: Record<string, string>;
  last_modified: string | null;
}

export interface AgentDefinition {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  agent_type: string;
  framework: string;
  system_prompt: string | null;
  model_config: Record<string, unknown>;
  tools: string[];
  parameters_schema: Record<string, unknown>;
  default_parameters: Record<string, unknown>;
  tags: string[];
  is_public: boolean;
  is_platform: boolean;
  org_id: string;
  created_by: string;
  creator_name: string | null;
  org_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgenticTask {
  id: string;
  agent_id: string | null;
  agentic_run_id: string | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  task: string;
  context: Record<string, unknown>;
  result: Record<string, unknown> | null;
  messages: Record<string, unknown>[];
  tool_calls: Record<string, unknown>[];
  error_message: string | null;
  tokens_used: number | null;
  started_at: string | null;
  finished_at: string | null;
  org_id: string;
  submitted_by: string;
  created_at: string;
  updated_at: string;
}

export interface AgenticRun {
  id: string;
  agent_id: string | null;
  title: string | null;
  summary: string | null;
  metadata: Record<string, unknown>;
  org_id: string;
  created_by: string;
  task_count: number;
  latest_task_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgenticRunDetail extends AgenticRun {
  tasks: AgenticTask[];
}

// Aliases for conversation-based naming used in agent-update branch
export type Conversation = AgenticRun;
export type AgentRun = AgenticTask;
export interface ConversationDetail extends AgenticRun {
  runs: AgenticTask[];
  tasks: AgenticTask[];
}

// --- Apps ---

export interface AppRecord {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  category: string;
  tags: string[];
  icon_url: string | null;
  thumbnail_url: string | null;
  launch_mode: "external" | "embedded";
  external_url: string | null;
  docker_image: string | null;
  docker_tag: string | null;
  container_port: number | null;
  env: Record<string, string>;
  resource_requirements: Record<string, unknown>;
  health_check_path: string | null;
  embed_sandbox: string | null;
  embed_allow: string | null;
  runtime_status:
    | "pending"
    | "building"
    | "deploying"
    | "active"
    | "failed"
    | "stopped";
  runtime_endpoint: string | null;
  last_deployed_at: string | null;
  last_build_error: string | null;
  auth_mode: "none" | "oidc" | "signed_jwt";
  oidc_client_id: string | null;
  launch_token_audience: string | null;
  launch_token_ttl_seconds: number | null;
  status: "draft" | "active" | "deprecated";
  is_public: boolean;
  org_id: string;
  created_by: string;
  creator_name: string | null;
  updated_by: string | null;
  updated_by_name: string | null;
  org_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppLaunchRecord {
  id: string;
  app_id: string;
  org_id: string;
  launched_by: string;
  launcher_name: string | null;
  launch_mode: string;
  auth_mode: string;
  client_ip: string | null;
  user_agent: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppLaunchResult {
  launch_mode: "external" | "embedded";
  launch_url: string;
  auth_mode: "none" | "oidc" | "signed_jwt";
  token: string | null;
  expires_at: string | null;
}

// --- Human Task Runs ---

export interface HumanTaskRun {
  id: string;
  tool_version_id: string;
  tool_run_id: string | null;
  pipeline_run_id: string | null;
  step_name: string | null;
  input_snapshot: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
  output_schema: Record<string, unknown>;
  input_schema: Record<string, unknown>;
  attachments: Record<string, unknown>[];
  status:
    | "pending"
    | "accepted"
    | "in_progress"
    | "completed"
    | "declined"
    | "cancelled"
    | "escalated";
  display_status: string;
  assigned_user_id: string | null;
  assigned_team_slug: string | null;
  project_lead_id: string | null;
  priority: string;
  finished_by: string | null;
  finished_at: string | null;
  due_at: string | null;
  escalated_at: string | null;
  escalated_to: string | null;
  delegation_history: Record<string, unknown>[];
  event_history: Array<{
    id: string;
    parent_event_id: string | null;
    action_type: string;
    event_type: string;
    actor: string | null;
    target: string | null;
    detail: string | null;
    message: string | null;
    occurred_at: string | null;
    payload: Record<string, unknown>;
    artifacts: Array<{
      id: string;
      file_name: string;
      file_size: number;
      storage_key: string;
      content_type: string | null;
    }>;
  }>;
  org_id: string;
  started_by: string;
  started_at: string;
  updated_at: string;
  // Denormalized display fields
  tool_slug: string | null;
  tool_id: string | null;
  tool_version_num: number | null;
  assigned_user_email: string | null;
  assigned_team_name: string | null;
  project_lead_email: string | null;
  finished_by_email: string | null;
  started_by_email: string | null;
  inputs: Array<{
    id: string;
    file_name: string;
    file_size: number;
    storage_key: string;
    status: string;
  }>;
}

export interface TaskRunSubmitPayload {
  output_data: Record<string, unknown>;
  message?: string;
  attachments?: {
    storage_path: string;
    file_name: string;
    content_type: string;
    file_size: number;
    parameter_name?: string;
  }[];
}

export interface TaskRunDelegatePayload {
  to_user_id: string;
  reason?: string;
  new_due_at?: string | null;
}

export async function apiPostTaskAction(
  taskRunId: string,
  message?: string,
  parentEventId?: string,
  file?: File,
): Promise<HumanTaskRun> {
  const formData = new FormData();
  if (message) formData.append("message", message);
  if (parentEventId) formData.append("parent_event_id", parentEventId);
  if (file) formData.append("file", file);
  const resp = await fetchWithRetry(`/api/v1/task-runs/${taskRunId}/actions`, {
    method: "POST",
    body: formData,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
}

/** Chat message for the assistant UI (client-side only) */
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  tool_calls?: { name: string; args: Record<string, unknown> }[];
  tool_results?: { name: string; result: string }[];
  delegation?: {
    agent_id: string;
    task: string;
    result?: string;
    status: "running" | "completed" | "failed";
  };
}
