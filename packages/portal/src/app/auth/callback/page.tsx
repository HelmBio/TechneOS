"use client";

import { apiPost, setTokens } from "@/lib/api";
import { useAuth, setLoginProvider } from "@/lib/auth";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

/**
 * OAuth2 callback handler for generic OAuth2 providers (e.g. PingFederate).
 *
 * The enterprise IdP redirects to /auth/callback?code=...&state=...
 * This page exchanges the authorization code for platform tokens via the
 * backend /token-exchange endpoint, then redirects to the home page.
 */
function CallbackContent() {
  const { refreshUser } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");

  const handleCallback = useCallback(async () => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");

    if (!code) {
      // Check for error response from IdP
      const errorParam = searchParams.get("error");
      const errorDesc = searchParams.get("error_description");
      setError(
        errorDesc || errorParam || "No authorization code received",
      );
      return;
    }

    // Verify state matches what we stored before redirect
    if (state) {
      const savedState = sessionStorage.getItem("techneos_oauth2_state");
      if (state !== savedState) {
        setError("Invalid state parameter — possible CSRF. Please try logging in again.");
        return;
      }
    }

    const redirectUri = sessionStorage.getItem("techneos_oauth2_redirect_uri") || "";
    const codeVerifier = sessionStorage.getItem("techneos_oauth2_code_verifier");

    // Clean up stored values
    sessionStorage.removeItem("techneos_oauth2_state");
    sessionStorage.removeItem("techneos_oauth2_redirect_uri");
    sessionStorage.removeItem("techneos_oauth2_code_verifier");

    try {
      const data = await apiPost<{
        access_token: string;
        refresh_token: string;
      }>("/api/v1/auth/token-exchange", {
        code,
        redirect_uri: redirectUri,
        code_verifier: codeVerifier,
        provider: "oauth2",
      });
      setTokens(data.access_token, data.refresh_token);
      setLoginProvider("oauth2");
      await refreshUser();
      router.push("/");
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "SSO login failed",
      );
    }
  }, [searchParams, router, refreshUser]);

  useEffect(() => {
    void (async () => {
      await handleCallback();
    })();
  }, [handleCallback]);

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="w-full max-w-sm space-y-4 rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-bold text-red-700">SSO Login Failed</h1>
          <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
          <button
            onClick={() => router.push("/login")}
            className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Back to login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="text-center">
        <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        <p className="text-gray-500">Completing sign in...</p>
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-gray-500">Loading...</p>
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
