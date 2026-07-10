import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockLogin = vi.fn();
const mockAuth = {
  user: null,
  loading: false,
  oidcConfig: { local: true, keycloak: null, oauth2: null } as import("@/lib/api").OIDCConfig | null,
  role: null,
  login: mockLogin,
  logout: vi.fn(),
  refreshUser: vi.fn(),
};

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockAuth,
  setLoginProvider: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiPost: vi.fn(),
  buildKeycloakLoginUrl: vi.fn(),
  buildOAuth2LoginUrl: vi.fn(),
  generatePKCE: vi.fn(),
  setTokens: vi.fn(),
}));

import LoginPage from "@/app/login/page";

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.loading = false;
    mockAuth.oidcConfig = { local: true, keycloak: null, oauth2: null };
  });

  it("renders sign in heading and email field", async () => {
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
      expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    });
  });

  it("shows register form when Register is clicked", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await waitFor(() => {
      expect(screen.getByText("Register")).toBeInTheDocument();
    });
    await user.click(screen.getByText("Register"));
    expect(screen.getByRole("heading", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Jane Doe")).toBeInTheDocument();
  });

  it("calls login on form submit", async () => {
    const user = userEvent.setup();
    mockLogin.mockResolvedValue(undefined);
    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText("you@example.com"), "a@b.com");
    // Password input — label isn't associated via htmlFor, so query directly
    const form = screen.getByPlaceholderText("you@example.com").closest("form")!;
    const passwordInput = form.querySelector("input[type='password']")!;
    await user.type(passwordInput, "password123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("a@b.com", "password123");
    });
  });

  it("shows loading state when auth is loading", () => {
    mockAuth.loading = true;
    mockAuth.oidcConfig = null;
    render(<LoginPage />);
    expect(screen.getAllByText("Loading...").length).toBeGreaterThan(0);
  });
});
