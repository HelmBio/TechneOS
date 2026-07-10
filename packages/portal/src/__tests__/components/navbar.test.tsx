import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { Navbar } from "@/components/navbar";

// Mock auth with configurable returns
const mockAuth = {
  user: null as import("@/lib/api").User | null,
  role: null as string | null,
  permissions: [] as string[],
  logout: vi.fn(),
  loading: false,
  oidcConfig: null,
  login: vi.fn(),
  refreshUser: vi.fn(),
};

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockAuth,
}));

// Mock notifications
vi.mock("@/components/notifications", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

// Mock useCollectionCounts
vi.mock("@/lib/use-collection-counts", () => ({
  useCollectionCounts: () => ({ datasets: 0, tools: 0, pipelines: 0, runs: 0, agents: 0 }),
}));

const baseUser: import("@/lib/api").User = {
  id: "u1",
  email: "test@example.com",
  full_name: "Test User",
  is_active: true,
  org_id: "org1",
  team_id: null,
  role_id: "r1",
  auth_method: "local",
  permissions: [],
  created_at: "",
  updated_at: "",
};

describe("Navbar (Sidebar)", () => {
  beforeEach(() => {
    mockAuth.user = null;
    mockAuth.role = null;
    mockAuth.logout.mockClear();
  });

  it("renders nothing when not authenticated", () => {
    const { container } = render(<Navbar />);
    expect(container.innerHTML).toBe("");
  });

  it("shows nav items when authenticated", () => {
    mockAuth.user = baseUser;
    render(<Navbar />);
    expect(screen.getByText("Datasets")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();
    expect(screen.getByText("Workflows")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(screen.getByText("Workflow Runs")).toBeInTheDocument();
    expect(screen.getByText("Agent Sessions")).toBeInTheDocument();
  });

  it("shows Admin link for org_admin role", () => {
    mockAuth.user = baseUser;
    mockAuth.role = "org_admin";
    mockAuth.permissions = ["org:update:org"];
    render(<Navbar />);
    // org_admin gets an "Admin" link pointing to /org-admin
    const adminLinks = screen.getAllByText("Admin");
    expect(adminLinks.length).toBeGreaterThanOrEqual(1);
  });

  it("hides org Admin link for platform_admin", () => {
    mockAuth.user = baseUser;
    mockAuth.role = "platform_admin";
    mockAuth.permissions = ["*:*:*"];
    render(<Navbar />);
    // platform_admin shows the platform Admin link (to /admin), not org-admin
    const adminLinks = screen.getAllByText("Admin");
    expect(adminLinks.length).toBe(1);
  });

  it("shows Admin link for platform_admin", () => {
    mockAuth.user = baseUser;
    mockAuth.role = "platform_admin";
    mockAuth.permissions = ["*:*:*"];
    render(<Navbar />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });

  it("hides Admin link for non-admin scientists", () => {
    mockAuth.user = baseUser;
    mockAuth.role = "scientist";
    mockAuth.permissions = [];
    render(<Navbar />);
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });

  it("renders as aside element", () => {
    mockAuth.user = baseUser;
    const { container } = render(<Navbar />);
    expect(container.querySelector("aside")).toBeInTheDocument();
  });
});
