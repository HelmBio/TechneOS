"use client";

import { useAuth, setLoginProvider } from "@/lib/auth";
import {
  apiPost,
  buildKeycloakLoginUrl,
  buildOAuth2LoginUrl,
  generatePKCE,
  setTokens,
  ssoErrorMessage,
} from "@/lib/api";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

function generateState(): string {
  // crypto.randomUUID() requires a secure context (HTTPS).
  // Fall back to crypto.getRandomValues for plain HTTP (e.g. LAN dev).
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function LoginContent() {
  const { login, oidcConfig, loading: authLoading, refreshUser } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const hasKeycloak = !!oidcConfig?.keycloak;
  const hasOAuth2 = !!oidcConfig?.oauth2;
  const isSecure =
    typeof crypto.subtle?.digest === "function";

  const showSSO = process.env.NEXT_PUBLIC_LOGIN_SSO === "true" && hasOAuth2 && isSecure;
  const showGoogle = process.env.NEXT_PUBLIC_LOGIN_GOOGLE === "true" && hasKeycloak && isSecure;
  const showGitHub = process.env.NEXT_PUBLIC_LOGIN_GITHUB === "true" && hasKeycloak && isSecure;
  const showAnySSO = showSSO || showGoogle || showGitHub;

  // Handle Keycloak OIDC callback (authorization code in URL).
  // Fires when Google/GitHub redirect back via Keycloak.
  const handleOIDCCallback = useCallback(async () => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    if (!code || !state) return;

    // Check if this is a Keycloak callback (techneos_oidc_state)
    const savedState = sessionStorage.getItem("techneos_oidc_state");
    if (state !== savedState) return;

    const codeVerifier = sessionStorage.getItem("techneos_oidc_code_verifier");
    sessionStorage.removeItem("techneos_oidc_state");
    sessionStorage.removeItem("techneos_oidc_code_verifier");

    setLoading(true);
    try {
      const data = await apiPost<{
        access_token: string;
        refresh_token: string;
      }>("/api/v1/auth/token-exchange", {
        code,
        redirect_uri: window.location.origin + "/login",
        code_verifier: codeVerifier,
        provider: "keycloak",
      });
      setTokens(data.access_token, data.refresh_token);
      setLoginProvider("keycloak");
      await refreshUser();
      router.push("/");
    } catch (err: unknown) {
      setError(ssoErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [searchParams, router, refreshUser]);

  useEffect(() => {
    handleOIDCCallback();
  }, [handleOIDCCallback]);

  const handleSSOLogin = async (idpHint?: string) => {
    if (!oidcConfig) return;
    setLoading(true);

    // Google/GitHub: go through Keycloak PKCE flow
    if (idpHint && oidcConfig.keycloak) {
      const { codeVerifier, codeChallenge } = await generatePKCE();
      const state = generateState();

      sessionStorage.setItem("techneos_oidc_code_verifier", codeVerifier);
      sessionStorage.setItem("techneos_oidc_state", state);

      const loginUrl = buildKeycloakLoginUrl(
        oidcConfig.keycloak,
        codeChallenge,
        window.location.origin + "/login",
        state,
        idpHint,
      );
      window.location.href = loginUrl;
      return;
    }

    // SSO button: go through OAuth2 flow (e.g. PingFederate)
    if (oidcConfig.oauth2) {
      const state = generateState();
      sessionStorage.setItem("techneos_oauth2_state", state);
      sessionStorage.setItem("techneos_oauth2_redirect_uri", oidcConfig.oauth2.redirect_uri);

      const loginUrl = buildOAuth2LoginUrl(oidcConfig.oauth2, state);
      window.location.href = loginUrl;
      return;
    }

    // Keycloak SSO (no idpHint, Keycloak is the only SSO provider)
    if (oidcConfig.keycloak) {
      const { codeVerifier, codeChallenge } = await generatePKCE();
      const state = generateState();

      sessionStorage.setItem("techneos_oidc_code_verifier", codeVerifier);
      sessionStorage.setItem("techneos_oidc_state", state);

      const loginUrl = buildKeycloakLoginUrl(
        oidcConfig.keycloak,
        codeChallenge,
        window.location.origin + "/login",
        state,
      );
      window.location.href = loginUrl;
      return;
    }
  };

  const handleLocalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "register") {
        await apiPost("/api/v1/auth/register", {
          email,
          password,
          full_name: fullName,
        });
      }
      await login(email, password);
      router.push("/");
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : `${mode === "register" ? "Registration" : "Login"} failed`,
      );
    } finally {
      setLoading(false);
    }
  };

  // Don't render until we know the auth mode
  if (authLoading || oidcConfig === null) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-sm space-y-4 rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-bold text-gray-900">
          {showAnySSO
            ? "Sign in"
            : mode === "login"
              ? "Sign in"
              : "Create account"}
        </h1>

        {error && (
          <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {showAnySSO ? (
          /* ── SSO / Social Login ────────────────────── */
          <>
            <div className="space-y-3">
              {/* Organization SSO */}
              {showSSO && (
                <button
                  type="button"
                  onClick={() => handleSSOLogin()}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-3 rounded-md border border-gray-300 bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
                  </svg>
                  Sign in with SSO
                </button>
              )}

              {/* Google */}
              {showGoogle && (
                <button
                  type="button"
                  onClick={() => handleSSOLogin("google")}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-3 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
                >
                  <svg className="h-5 w-5" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                  </svg>
                  Sign in with Google
                </button>
              )}

              {/* GitHub */}
              {showGitHub && (
                <button
                  type="button"
                  onClick={() => handleSSOLogin("github")}
                  disabled={loading}
                  className="flex w-full items-center justify-center gap-3 rounded-md border border-gray-300 bg-gray-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-800 disabled:opacity-50"
                >
                  <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
                    <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
                  </svg>
                  Sign in with GitHub
                </button>
              )}
            </div>

            <div className="relative py-2">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-200" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-white px-2 text-gray-400">or</span>
              </div>
            </div>
            {/* Still allow email/password as a fallback */}
            <form onSubmit={handleLocalSubmit} className="space-y-3">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="Email"
                className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="Password"
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 pr-10 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-4 w-4">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12c1.292 4.338 5.31 7.5 10.066 7.5.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-4 w-4">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                    </svg>
                  )}
                </button>
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {loading ? "Signing in..." : "Sign in with email"}
              </button>
              <p className="text-center text-xs text-gray-400">
                Forgot your password? Contact your platform administrator.
              </p>
            </form>
          </>
        ) : (
          /* ── Local Login ────────────────────────────── */
          <form onSubmit={handleLocalSubmit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Full Name
                </label>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  placeholder="Jane Doe"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@example.com"
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">
                Password
              </label>
              <div className="relative mt-1">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  placeholder={
                    mode === "register" ? "Min. 8 characters" : ""
                  }
                  className="block w-full rounded-md border border-gray-300 px-3 py-2 pr-10 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth={1.5}
                      stroke="currentColor"
                      className="h-4 w-4"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12c1.292 4.338 5.31 7.5 10.066 7.5.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88"
                      />
                    </svg>
                  ) : (
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth={1.5}
                      stroke="currentColor"
                      className="h-4 w-4"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z"
                      />
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
                      />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading
                ? mode === "login"
                  ? "Signing in..."
                  : "Creating account..."
                : mode === "login"
                  ? "Sign in"
                  : "Create account"}
            </button>

            {mode === "login" && (
              <p className="text-center text-xs text-gray-400">
                Forgot your password? Contact your platform administrator.
              </p>
            )}

            <p className="text-center text-sm text-gray-500">
              {mode === "login" ? (
                <>
                  Don&apos;t have an account?{" "}
                  <button
                    type="button"
                    onClick={() => {
                      setMode("register");
                      setError("");
                    }}
                    className="font-medium text-blue-600 hover:underline"
                  >
                    Register
                  </button>
                </>
              ) : (
                <>
                  Already have an account?{" "}
                  <button
                    type="button"
                    onClick={() => {
                      setMode("login");
                      setError("");
                    }}
                    className="font-medium text-blue-600 hover:underline"
                  >
                    Sign in
                  </button>
                </>
              )}
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-gray-500">Loading...</p>
        </div>
      }
    >
      <LoginContent />
    </Suspense>
  );
}
