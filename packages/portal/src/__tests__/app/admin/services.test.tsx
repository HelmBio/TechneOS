import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockApiGet = vi.fn();
vi.mock("@/lib/api", () => ({
  apiGet: (...args: unknown[]) => mockApiGet(...args),
}));

import AdminServicesPage from "@/app/admin/services/page";

describe("AdminServicesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows loading state", () => {
    mockApiGet.mockReturnValue(new Promise(() => {}));
    render(<AdminServicesPage />);
    expect(screen.getByText("Checking service health...")).toBeInTheDocument();
  });

  it("renders services table after loading", async () => {
    const services = [
      { name: "auth", url: "http://localhost:8001", status: "healthy", latency_ms: 15 },
      { name: "gateway", url: "http://localhost:8000", status: "unhealthy", latency_ms: null },
    ];
    mockApiGet.mockResolvedValue(services);

    render(<AdminServicesPage />);

    await waitFor(() => {
      expect(screen.getByText("auth")).toBeInTheDocument();
      expect(screen.getByText("gateway")).toBeInTheDocument();
      expect(screen.getByText("15 ms")).toBeInTheDocument();
      expect(screen.getByText(/services healthy/)).toBeInTheDocument();
    });
  });

  it("has a Logs button per service row", async () => {
    mockApiGet.mockResolvedValue([
      { name: "auth", url: "http://localhost:8001", status: "healthy", latency_ms: 5 },
    ]);
    render(<AdminServicesPage />);

    await waitFor(() => {
      expect(screen.getByText("Logs")).toBeInTheDocument();
    });
  });
});
