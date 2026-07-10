import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockApiGet = vi.fn();
const mockAuth = {
  user: null as import("@/lib/api").User | null,
  role: null as string | null,
  loading: false,
  oidcConfig: null,
  login: vi.fn(),
  logout: vi.fn(),
  refreshUser: vi.fn(),
};

vi.mock("@/lib/api", () => ({
  apiGet: (...args: unknown[]) => mockApiGet(...args),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockAuth,
}));

import OrgAdminOverviewPage from "@/app/org-admin/page";

const baseUser: import("@/lib/api").User = {
  id: "u1",
  email: "admin@org.com",
  full_name: "Org Admin",
  is_active: true,
  org_id: "org-1",
  team_id: null,
  role_id: "r1",
  auth_method: "local",
  permissions: [],
  created_at: "",
  updated_at: "",
};

describe("OrgAdminOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.user = null;
    mockAuth.role = null;
  });

  it("shows message when user has no org", async () => {
    mockAuth.user = { ...baseUser, org_id: null };
    render(<OrgAdminOverviewPage />);
    await waitFor(() => {
      expect(screen.getByText(/not assigned to an organization/)).toBeInTheDocument();
    });
  });

  it("renders org info and stats", async () => {
    mockAuth.user = baseUser;
    mockApiGet.mockImplementation((path: string) => {
      if (path.includes("/orgs/org-1") && !path.includes("teams"))
        return Promise.resolve({
          id: "org-1",
          name: "Acme Corp",
          slug: "acme",
          description: "A test org",
          settings: {},
          is_active: true,
          created_at: "2025-01-01T00:00:00Z",
          updated_at: "2025-01-01T00:00:00Z",
        });
      if (path.includes("/users"))
        return Promise.resolve({ items: [], total: 12, skip: 0, limit: 1 });
      if (path.includes("/teams"))
        return Promise.resolve({ items: [], total: 3, skip: 0, limit: 1 });
      return Promise.reject(new Error("unknown"));
    });

    render(<OrgAdminOverviewPage />);

    await waitFor(() => {
      expect(screen.getByText("Acme Corp")).toBeInTheDocument();
      expect(screen.getByText("12")).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
      expect(screen.getByText("active")).toBeInTheDocument();
    });
  });
});
