import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock api
const mockApiGet = vi.fn();
vi.mock("@/lib/api", () => ({
  apiGet: (...args: unknown[]) => mockApiGet(...args),
}));

import AdminDashboard from "@/app/admin/page";

describe("AdminDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockApiGet.mockReturnValue(new Promise(() => {})); // never resolves
    render(<AdminDashboard />);
    expect(screen.getByText("Loading dashboard...")).toBeInTheDocument();
  });

  it("renders stats after loading", async () => {
    const stats = {
      total_users: 42,
      active_users: 30,
      total_orgs: 5,
      active_orgs: 3,
      total_teams: 8,
      total_roles: 4,
      total_llm_providers: 2,
      default_llm_providers: 1,
    };
    mockApiGet.mockResolvedValue(stats);

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText("42")).toBeInTheDocument();
      expect(screen.getByText("Users")).toBeInTheDocument();
      expect(screen.getByText("Organizations")).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
    });
  });
});
