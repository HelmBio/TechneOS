"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  apiGet,
  apiPost,
  clearTokens,
  consumeSessionExpiredFlag,
  emitSessionExpired,
  getOIDCConfig,
  getTokenClaims,
  isLoggedIn,
  refreshTokenOnce,
  setTokens,
  type OIDCConfig,
  type User,
} from "@/lib/api";

interface AuthContextType {
  user: User | null;
  loading: boolean;
  oidcConfig: OIDCConfig | null;
  /** The user's RBAC role name from the JWT (e.g. "platform_admin", "org_admin"). */
  role: string | null;
  /** The user's resolved permissions from the JWT or /me endpoint. */
  permissions: string[];
  /** Increments on every token refresh — use as a dependency to re-fetch data. */
  tokenVersion: number;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Re-fetch the current user from the backend (call after storing tokens externally). */
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  oidcConfig: null,
  role: null,
  permissions: [],
  tokenVersion: 0,
  login: async () => {},
  logout: () => {},
  refreshUser: async () => {},
});

/** Track which provider the user logged in with so logout can revoke correctly. */
export function setLoginProvider(provider: string) {
  if (typeof window !== "undefined") {
    sessionStorage.setItem("techneos_login_provider", provider);
  }
}

function getLoginProvider(): string | null {
  if (typeof window !== "undefined") {
    return sessionStorage.getItem("techneos_login_provider");
  }
  return null;
}

function clearLoginProvider() {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem("techneos_login_provider");
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [oidcConfig, setOidcConfig] = useState<OIDCConfig | null>(null);
  const [tokenVersion, setTokenVersion] = useState(0);

  // Bump tokenVersion whenever a token refresh occurs so dependent
  // components re-fetch with the new token automatically.
  useEffect(() => {
    const onRefreshed = () => setTokenVersion((v) => v + 1);
    window.addEventListener("token-refreshed", onRefreshed);
    return () => window.removeEventListener("token-refreshed", onRefreshed);
  }, []);

  // Clear user state when session expires so the navbar/profile dropdown
  // doesn't show the previously logged-in user behind the expiry modal.
  useEffect(() => {
    const onSessionExpired = () => setUser(null);
    window.addEventListener("session-expired", onSessionExpired);
    return () => window.removeEventListener("session-expired", onSessionExpired);
  }, []);

  const fetchUser = useCallback(async () => {
    if (!isLoggedIn()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const u = await apiGet<User>("/api/v1/auth/me");
      setUser(u);
    } catch {
      clearTokens();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetch OIDC config to determine available login providers
    getOIDCConfig()
      .then(setOidcConfig)
      .catch(() => setOidcConfig({ local: true, keycloak: null, oauth2: null }));
    fetchUser();
  }, [fetchUser]);

  // ── User activity tracking ─────────────────────────────────
  // Track last user interaction so we can auto-refresh for active users.
  const lastActivityRef = useRef(Date.now());

  useEffect(() => {
    if (!user) return;
    const ACTIVITY_EVENTS = ["click", "keydown", "mousemove", "scroll", "touchstart"] as const;
    const onActivity = () => { lastActivityRef.current = Date.now(); };
    for (const evt of ACTIVITY_EVENTS) window.addEventListener(evt, onActivity, { passive: true });
    return () => { for (const evt of ACTIVITY_EVENTS) window.removeEventListener(evt, onActivity); };
  }, [user]);

  // ── Proactive token expiry check ──────────────────────────
  // If the user was active in the last 5 minutes, auto-refresh.
  // Otherwise show the expiry banner so they can manually extend.
  useEffect(() => {
    if (!user) return;
    const CHECK_INTERVAL = (Number(process.env.NEXT_PUBLIC_SESSION_CHECK_INTERVAL) || 300) * 1000;
    const WARN_BEFORE = Number(process.env.NEXT_PUBLIC_SESSION_WARN_BEFORE) || 1800;
    const AUTO_REFRESH_BEFORE = Number(process.env.NEXT_PUBLIC_SESSION_AUTO_REFRESH_BEFORE) || 300;
    const AUTO_REFRESH_ACTIVE = (Number(process.env.NEXT_PUBLIC_SESSION_AUTO_REFRESH_ACTIVE) || 300) * 1000;

    const check = async () => {
      const claims = getTokenClaims();
      if (!claims?.exp) return;
      const secsLeft = claims.exp - Math.floor(Date.now() / 1000);
      if (secsLeft <= 0) {
        emitSessionExpired();
        clearInterval(timer);
        return;
      }
      // Silent auto-refresh if token expires within 5 min and user was recently active
      if (secsLeft <= AUTO_REFRESH_BEFORE) {
        const idleMs = Date.now() - lastActivityRef.current;
        if (idleMs < AUTO_REFRESH_ACTIVE) {
          const ok = await refreshTokenOnce();
          if (!ok) {
            emitSessionExpired();
            clearInterval(timer);
          }
          return;
        }
      }
      // Always show the banner so the user can decide whether to extend
      if (secsLeft <= WARN_BEFORE) {
        window.dispatchEvent(
          new CustomEvent("session-expiring", { detail: { secondsLeft: secsLeft } }),
        );
      }
    };

    const timer = setInterval(check, CHECK_INTERVAL);
    // Run once immediately to catch already-expiring tokens on mount
    check();

    return () => clearInterval(timer);
  }, [user]);

  const login = async (email: string, password: string) => {
    const data = await apiPost<{
      access_token: string;
      refresh_token: string;
    }>("/api/v1/auth/login", { email, password, auth_method: "local" });
    setTokens(data.access_token, data.refresh_token);
    setLoginProvider("local");
    await fetchUser();
  };

  // Derive role and permissions from JWT claims
  const claims = getTokenClaims();
  const role = claims?.role ?? null;
  const permissions = claims?.permissions ?? user?.permissions ?? [];

  const logout = () => {
    const refresh = typeof window !== "undefined"
      ? localStorage.getItem("techneos_refresh_token")
      : null;
    const loginProv = getLoginProvider();

    // Revoke Keycloak session if the user logged in via Keycloak
    if (refresh && loginProv === "keycloak") {
      apiPost("/api/v1/auth/logout", {
        refresh_token: refresh,
        provider: "keycloak",
      }).catch(() => {});
    }

    clearTokens();
    clearLoginProvider();
    setUser(null);

    // Redirect to Keycloak end-session if user logged in via Keycloak
    if (loginProv === "keycloak" && oidcConfig?.keycloak?.end_session_endpoint) {
      const redirectUri = encodeURIComponent(window.location.origin + "/login");
      window.location.href = `${oidcConfig.keycloak.end_session_endpoint}?post_logout_redirect_uri=${redirectUri}&client_id=${oidcConfig.keycloak.client_id}`;
      return;
    }

    // Local logout — full reload to /login so any in-memory state (iframes,
    // streams, cached page data) is torn down rather than left in the DOM.
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, oidcConfig, role, permissions, tokenVersion, login, logout, refreshUser: fetchUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

// ── Session expiry UI components ────────────────────────────

function formatTimeLeft(seconds: number): string {
  if (seconds >= 120) return `${Math.ceil(seconds / 60)} minutes`;
  if (seconds >= 60) return "1 minute";
  return `${seconds} seconds`;
}

/**
 * Top notification banner shown when the token is about to expire.
 * Offers an "Extend session" button that uses the refresh token.
 * Dismisses automatically when the token is refreshed.
 */
export function SessionExpiryBanner() {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [extending, setExtending] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    function onExpiring(e: Event) {
      const secs = (e as CustomEvent).detail?.secondsLeft as number;
      setSecondsLeft(secs);
      setDismissed(false);
    }
    function onExpired() {
      // Clear the banner when the session has fully expired so it does
      // not overlap with the SessionExpiredAlert modal.
      setSecondsLeft(null);
    }
    window.addEventListener("session-expiring", onExpiring);
    window.addEventListener("session-expired", onExpired);
    return () => {
      window.removeEventListener("session-expiring", onExpiring);
      window.removeEventListener("session-expired", onExpired);
    };
  }, []);

  const extendSession = async () => {
    setExtending(true);
    const ok = await refreshTokenOnce();
    setExtending(false);
    if (ok) {
      setSecondsLeft(null);
      setDismissed(false);
    } else {
      // Refresh failed — show the full expired modal
      emitSessionExpired();
      setSecondsLeft(null);
    }
  };

  if (secondsLeft === null || dismissed) return null;

  return (
    <div className="fixed top-2 left-1/2 -translate-x-1/2 z-[90] rounded-lg bg-amber-50 border border-amber-200 px-4 py-2.5 shadow-md">
      <div className="flex items-center gap-3 text-sm whitespace-nowrap">
        <svg className="h-4 w-4 shrink-0 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span className="text-amber-800">
          Your session will expire in <strong>{formatTimeLeft(secondsLeft)}</strong>.
        </span>
        <button
          onClick={extendSession}
          disabled={extending}
          className="rounded-md bg-amber-600 px-3 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
        >
          {extending ? "Extending..." : "Extend session"}
        </button>
        <button
          onClick={() => setDismissed(true)}
          className="ml-1 text-amber-500 hover:text-amber-700"
          aria-label="Dismiss"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/** Modal alert shown when the session token has fully expired and refresh failed. */
export function SessionExpiredAlert() {
  // Lazy initializer checks the flag exactly once, before the first paint —
  // equivalent to the old mount-time check but without a setState-in-effect.
  const [visible, setVisible] = useState(() => consumeSessionExpiredFlag());

  useEffect(() => {
    function onExpired() {
      setVisible(true);
    }
    window.addEventListener("session-expired", onExpired);
    return () => window.removeEventListener("session-expired", onExpired);
  }, []);

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40">
      <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-center gap-3 mb-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-100">
            <svg className="h-5 w-5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
          </div>
          <h3 className="text-base font-semibold text-gray-900">Session Expired</h3>
        </div>
        <p className="text-sm text-gray-600 mb-5">
          Your session has expired and could not be refreshed. Please sign in again to continue.
        </p>
        <button
          onClick={() => {
            // Pre-fill email only for local (non-SSO) users
            const claims = getTokenClaims();
            const isLocal = getLoginProvider() === "local";
            const emailParam = isLocal && claims?.email ? `?email=${encodeURIComponent(claims.email)}` : "";
            setVisible(false);
            clearTokens();
            window.location.href = `/login${emailParam}`;
          }}
          className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
        >
          Sign in again
        </button>
      </div>
    </div>
  );
}
