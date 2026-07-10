import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  ApiError,
  setTokens,
  clearTokens,
  isLoggedIn,
  getTokenClaims,
} from "@/lib/api";

describe("ApiError", () => {
  it("stores status and detail", () => {
    const err = new ApiError(404, "Not Found");
    expect(err.status).toBe(404);
    expect(err.detail).toBe("Not Found");
    expect(err.message).toBe("HTTP 404: Not Found");
  });

  it("is an instance of Error", () => {
    const err = new ApiError(500, "Server Error");
    expect(err).toBeInstanceOf(Error);
  });
});

describe("Token management", () => {
  it("setTokens stores tokens in localStorage", () => {
    setTokens("access123", "refresh456");
    expect(localStorage.getItem("techneos_access_token")).toBe("access123");
    expect(localStorage.getItem("techneos_refresh_token")).toBe("refresh456");
  });

  it("clearTokens removes tokens from localStorage", () => {
    setTokens("access123", "refresh456");
    clearTokens();
    expect(localStorage.getItem("techneos_access_token")).toBeNull();
    expect(localStorage.getItem("techneos_refresh_token")).toBeNull();
  });

  it("isLoggedIn returns true when token exists", () => {
    setTokens("access123", "refresh456");
    expect(isLoggedIn()).toBe(true);
  });

  it("isLoggedIn returns false when no token", () => {
    expect(isLoggedIn()).toBe(false);
  });
});

describe("getTokenClaims", () => {
  it("returns null when no token", () => {
    expect(getTokenClaims()).toBeNull();
  });

  it("returns null for malformed token", () => {
    localStorage.setItem("techneos_access_token", "not-a-jwt");
    expect(getTokenClaims()).toBeNull();
  });

  it("returns null for token with only 2 parts", () => {
    localStorage.setItem("techneos_access_token", "header.payload");
    expect(getTokenClaims()).toBeNull();
  });

  it("decodes valid JWT payload", () => {
    const payload = {
      sub: "user-123",
      email: "test@example.com",
      role: "org_admin",
      org_id: "org-456",
      team_id: "team-789",
    };
    const encoded = btoa(JSON.stringify(payload));
    const fakeJwt = `header.${encoded}.signature`;
    localStorage.setItem("techneos_access_token", fakeJwt);

    const claims = getTokenClaims();
    expect(claims).toEqual({
      sub: "user-123",
      email: "test@example.com",
      role: "org_admin",
      org_id: "org-456",
      team_id: "team-789",
      permissions: [],
      exp: null,
    });
  });

  it("defaults missing fields to empty string / null", () => {
    const payload = { sub: "user-123" };
    const encoded = btoa(JSON.stringify(payload));
    const fakeJwt = `header.${encoded}.signature`;
    localStorage.setItem("techneos_access_token", fakeJwt);

    const claims = getTokenClaims();
    expect(claims).toEqual({
      sub: "user-123",
      email: "",
      role: null,
      org_id: null,
      team_id: null,
      permissions: [],
      exp: null,
    });
  });

  it("handles base64url encoded payloads (- and _ chars)", () => {
    const payload = { sub: "user+/=id", email: "a@b.com" };
    // Manually encode with base64url
    const base64 = btoa(JSON.stringify(payload));
    const base64url = base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
    const fakeJwt = `header.${base64url}.signature`;
    localStorage.setItem("techneos_access_token", fakeJwt);

    const claims = getTokenClaims();
    expect(claims?.sub).toBe("user+/=id");
  });

  it("returns null on invalid base64 in payload", () => {
    const fakeJwt = "header.!!!invalid!!!.signature";
    localStorage.setItem("techneos_access_token", fakeJwt);
    expect(getTokenClaims()).toBeNull();
  });
});
