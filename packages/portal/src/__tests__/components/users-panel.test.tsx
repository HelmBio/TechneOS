import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import UsersPanel from "@/components/users-panel";
import { apiDelete, apiGet } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiGet: vi.fn(), apiDelete: vi.fn() };
});

const ssoUser: import("@/lib/api").User = {
  id: "u1",
  email: "new.user+gh@example.com",
  full_name: "New User",
  is_active: false,
  org_id: "org1",
  team_id: null,
  role_id: null,
  auth_method: "sso",
  permissions: [],
  created_at: "2026-10-04T00:00:00Z",
  updated_at: "2026-10-04T00:00:00Z",
};

function renderPanel(deleteApiPrefix?: string) {
  return render(
    <UsersPanel
      usersApiPath="/api/v1/admin/users"
      updateApiPrefix="/api/v1/admin/users"
      rolesApiPath="/api/v1/admin/roles"
      deleteApiPrefix={deleteApiPrefix}
    />,
  );
}

describe("UsersPanel delete", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockImplementation(async (path: string) =>
      path.endsWith("/roles") ? [] : { items: [ssoUser], total: 1 },
    );
    vi.mocked(apiDelete).mockReset().mockResolvedValue(undefined);
  });

  it("hides Delete when no delete endpoint is given", async () => {
    renderPanel();
    await screen.findByText(ssoUser.email);
    expect(screen.queryByLabelText("Delete user")).toBeNull();
  });

  it("deletes an SSO user by encoded email after confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel("/api/v1/admin/users/by-email");
    fireEvent.click(await screen.findByLabelText("Delete user"));

    expect(confirm.mock.calls[0][0]).toContain("sign-in account is removed too");
    await waitFor(() =>
      expect(apiDelete).toHaveBeenCalledWith(
        "/api/v1/admin/users/by-email/new.user%2Bgh%40example.com",
      ),
    );
  });

  it("disables Delete for admin users", async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) =>
      path.endsWith("/roles")
        ? [{ id: "r-admin", name: "org_admin" }]
        : { items: [{ ...ssoUser, role_id: "r-admin" }], total: 1 },
    );
    renderPanel("/api/v1/admin/users/by-email");
    const button = await screen.findByLabelText("Delete user");
    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    expect(apiDelete).not.toHaveBeenCalled();
  });

  it("does nothing when the confirmation is cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPanel("/api/v1/admin/users/by-email");
    fireEvent.click(await screen.findByLabelText("Delete user"));
    expect(apiDelete).not.toHaveBeenCalled();
  });
});
