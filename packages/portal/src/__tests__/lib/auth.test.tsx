import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { setTokens } from "@/lib/api";

// Mock the api module partially — keep real token functions, mock network calls
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPost: vi.fn(),
    getOIDCConfig: vi.fn().mockResolvedValue({ local: true, keycloak: null, oauth2: null }),
  };
});

import { apiGet } from "@/lib/api";
const mockApiGet = vi.mocked(apiGet);

function TestConsumer() {
  const { user, loading, role } = useAuth();
  if (loading) return <div>loading</div>;
  if (!user) return <div>no user</div>;
  return (
    <div>
      <span data-testid="email">{user.email}</span>
      <span data-testid="role">{role ?? "none"}</span>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows no user when not logged in", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("no user")).toBeInTheDocument();
    });
  });

  it("fetches user when token exists", async () => {
    const fakeUser = {
      id: "u1",
      email: "test@example.com",
      full_name: "Test User",
      is_active: true,
      org_id: null,
      team_id: null,
      role_id: null,
      auth_method: "local",
      permissions: [],
      created_at: "",
      updated_at: "",
    };
    mockApiGet.mockResolvedValueOnce(fakeUser);

    // Set a token with role claim
    const payload = { sub: "u1", email: "test@example.com", role: "scientist" };
    const encoded = btoa(JSON.stringify(payload));
    localStorage.setItem("techneos_access_token", `h.${encoded}.s`);
    localStorage.setItem("techneos_refresh_token", "refresh");

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("email")).toHaveTextContent("test@example.com");
      expect(screen.getByTestId("role")).toHaveTextContent("scientist");
    });
  });

  it("clears user when apiGet fails", async () => {
    mockApiGet.mockRejectedValueOnce(new Error("Unauthorized"));
    localStorage.setItem("techneos_access_token", "bad-token");
    localStorage.setItem("techneos_refresh_token", "refresh");

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("no user")).toBeInTheDocument();
    });
    // Token should be cleared
    expect(localStorage.getItem("techneos_access_token")).toBeNull();
  });
});
