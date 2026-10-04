"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  type AdminUserUpdatePayload,
  type Org,
  type PaginatedResponse,
  type Role,
  type Team,
  type User,
} from "@/lib/api";

const PROTECTED_ROLES = ["platform_admin", "org_admin"];

interface UsersPanelProps {
  /** API endpoint to list/search users. */
  usersApiPath: string;
  /** API endpoint to update a user (user id is appended). */
  updateApiPrefix: string;
  /** API endpoint to create a new user. */
  createApiPath?: string;
  /** API endpoint to delete a user (URL-encoded email is appended). Hides Delete when unset. */
  deleteApiPrefix?: string;
  /** API endpoint to list roles. */
  rolesApiPath: string;
  /** Show Org column + org selector in edit (platform admin). */
  showOrg?: boolean;
  /** API path to list orgs (required when showOrg=true). */
  orgsApiPath?: string;
  /** Show Team column + team selector in edit (org admin). */
  showTeam?: boolean;
  /** API path to list teams (required when showTeam=true). */
  teamsApiPath?: string;
  /** Filter roles — e.g. org admins can't assign platform_admin. */
  excludeRoles?: string[];
}

export default function UsersPanel({
  usersApiPath,
  updateApiPrefix,
  createApiPath,
  deleteApiPrefix,
  rolesApiPath,
  showOrg = false,
  orgsApiPath,
  showTeam = false,
  teamsApiPath,
  excludeRoles = [],
}: UsersPanelProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  // Reference data for dropdowns
  const [roles, setRoles] = useState<Role[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);

  // Edit modal state
  const [editUser, setEditUser] = useState<User | null>(null);
  const [editForm, setEditForm] = useState<AdminUserUpdatePayload>({});
  const [saving, setSaving] = useState(false);

  // Create user form state
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    full_name: "",
    email: "",
    password: "",
    role_name: "",
    org_id: "",
    team_id: "",
    is_active: true,
  });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showCreateTooltip, setShowCreateTooltip] = useState(false);
  const [createTooltipAlign, setCreateTooltipAlign] = useState<"center" | "left" | "right">("center");
  const createButtonRef = useRef<HTMLButtonElement>(null);

  // Reset password modal state
  const [resetUser, setResetUser] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetConfirm, setResetConfirm] = useState("");
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetSuccess, setResetSuccess] = useState(false);

  const limit = 20;

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        skip: String(page * limit),
        limit: String(limit),
      };
      if (search) params.search = search;
      const data = await apiGet<PaginatedResponse<User>>(
        usersApiPath,
        params,
      );
      setUsers(data.items);
      setTotal(data.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [usersApiPath, page, search]);

  useEffect(() => {
    fetchUsers();
    const onRefreshed = () => fetchUsers();
    window.addEventListener("token-refreshed", onRefreshed);
    return () => window.removeEventListener("token-refreshed", onRefreshed);
  }, [fetchUsers]);

  useEffect(() => {
    if (showCreateTooltip && createButtonRef.current) {
      const button = createButtonRef.current;
      const rect = button.getBoundingClientRect();
      const tooltipWidth = 200;
      const spaceRight = window.innerWidth - rect.right;
      const spaceLeft = rect.left;
      if (spaceRight < tooltipWidth && spaceLeft > spaceRight) {
        setCreateTooltipAlign("right");
      } else if (spaceRight < tooltipWidth) {
        setCreateTooltipAlign("left");
      } else {
        setCreateTooltipAlign("center");
      }
    }
  }, [showCreateTooltip]);

  // Load reference data once
  useEffect(() => {
    apiGet<Role[]>(rolesApiPath).then(setRoles).catch(console.error);
    if (showOrg && orgsApiPath) {
      apiGet<PaginatedResponse<Org>>(orgsApiPath, { limit: "200" })
        .then((d) => setOrgs(d.items))
        .catch(console.error);
    }
    if (showTeam && teamsApiPath) {
      apiGet<PaginatedResponse<Team>>(teamsApiPath, { limit: "200" })
        .then((d) => setTeams(d.items))
        .catch(console.error);
    }
  }, [rolesApiPath, showOrg, orgsApiPath, showTeam, teamsApiPath]);

  const openEdit = (u: User) => {
    setEditUser(u);
    const roleName = roles.find((r) => r.id === u.role_id)?.name ?? null;
    setEditForm({
      full_name: u.full_name,
      email: u.email,
      is_active: u.is_active,
      ...(showOrg ? { org_id: u.org_id } : {}),
      ...(showTeam ? { team_id: u.team_id } : {}),
      role_name: roleName,
    });
  };

  const saveEdit = async () => {
    if (!editUser) return;
    setSaving(true);
    try {
      await apiPut<User>(`${updateApiPrefix}/${editUser.id}`, editForm);
      setEditUser(null);
      fetchUsers();
    } catch (e) {
      console.error(e);
      alert("Failed to update user");
    } finally {
      setSaving(false);
    }
  };

  const openResetPassword = (u: User) => {
    setResetUser(u);
    setResetPassword("");
    setResetConfirm("");
    setShowResetPassword(false);
    setResetError(null);
    setResetSuccess(false);
    setResetting(false);
  };

  const submitResetPassword = async () => {
    if (!resetUser) return;
    setResetError(null);

    if (resetPassword.length < 8) {
      setResetError("Password must be at least 8 characters");
      return;
    }
    if (resetPassword !== resetConfirm) {
      setResetError("Passwords do not match");
      return;
    }

    setResetting(true);
    try {
      await apiPut(`${updateApiPrefix}/${resetUser.id}/reset-password`, {
        new_password: resetPassword,
      });
      setResetSuccess(true);
    } catch (e) {
      console.error(e);
      setResetError("Failed to reset password");
    } finally {
      setResetting(false);
    }
  };

  const totalPages = Math.ceil(total / limit);
  const roleName = (roleId: string | null) =>
    roles.find((r) => r.id === roleId)?.name ?? "-";
  const orgName = (orgId: string | null) =>
    orgs.find((o) => o.id === orgId)?.name ?? "-";
  const teamName = (teamId: string | null) =>
    teams.find((t) => t.id === teamId)?.name ?? "-";

  const assignableRoles = roles.filter(
    (r) => !excludeRoles.includes(r.name),
  );

  const toggleUserActive = async (u: User) => {
    try {
      await apiPut<User>(`${updateApiPrefix}/${u.id}`, {
        is_active: !u.is_active,
      });
      fetchUsers();
    } catch (e) {
      console.error("Failed to toggle user status", e);
    }
  };

  // Admins can't be deleted (the API refuses too); their Delete button is disabled.
  const isProtected = (u: User) => PROTECTED_ROLES.includes(roleName(u.role_id));

  const deleteUser = async (u: User) => {
    if (!deleteApiPrefix || isProtected(u)) return;
    const sso = u.auth_method === "sso" ? " Their sign-in account is removed too." : "";
    if (
      !window.confirm(
        `Permanently delete ${u.email} and everything they created (pipelines, tools, datasets, runs)?${sso} This can't be undone.`,
      )
    ) {
      return;
    }
    try {
      await apiDelete(`${deleteApiPrefix}/${encodeURIComponent(u.email)}`);
      fetchUsers();
    } catch (e) {
      alert(e instanceof ApiError ? e.detail : "Failed to delete user");
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createApiPath) return;
    setCreateError(null);
    if (!createForm.full_name || !createForm.email || !createForm.password) {
      setCreateError("Full Name, Email, and Password are required");
      return;
    }
    if (createForm.password.length < 8) {
      setCreateError("Password must be at least 8 characters");
      return;
    }
    setCreating(true);
    try {
      await apiPost(createApiPath, {
        full_name: createForm.full_name,
        email: createForm.email,
        password: createForm.password,
        role_name: createForm.role_name || null,
        org_id: createForm.org_id || undefined,
        team_id: createForm.team_id || null,
        is_active: createForm.is_active,
      });
      setShowCreate(false);
      setCreateForm({
        full_name: "",
        email: "",
        password: "",
        role_name: "",
        org_id: "",
        team_id: "",
        is_active: true,
      });
      fetchUsers();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to create user";
      setCreateError(msg);
    } finally {
      setCreating(false);
    }
  };

  const resetCreateForm = () => {
    setShowCreate(false);
    setCreateError(null);
    setCreateForm({
      full_name: "",
      email: "",
      password: "",
      role_name: "",
      org_id: "",
      team_id: "",
      is_active: true,
    });
  };

  const colCount =
    6 + (showOrg ? 1 : 0) + (showTeam ? 1 : 0);

  return (
    <div>
      {/* Search + Create */}
      <div className="mb-4 flex items-center gap-3">
        <input
          type="text"
          placeholder="Search by name or email..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          className="w-80 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <span className="text-sm text-gray-500">{total} users</span>
        {createApiPath && (
          <div className="relative ml-auto">
            <button
              ref={createButtonRef}
              onClick={() => {
                setShowCreate(!showCreate);
                setCreateError(null);
              }}
              className="rounded-md border border-gray-300 p-1.5 text-gray-500 hover:border-gray-400 hover:bg-gray-100 hover:text-gray-700"
              onMouseEnter={() => setShowCreateTooltip(true)}
              onMouseLeave={() => setShowCreateTooltip(false)}
              onFocus={() => setShowCreateTooltip(true)}
              onBlur={() => setShowCreateTooltip(false)}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="h-4 w-4"
              >
                <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
              </svg>
            </button>
            {showCreateTooltip && (
              <div
                className={`absolute top-full mt-2 w-max rounded-md bg-gray-900 px-3 py-1.5 text-xs text-white shadow-lg opacity-100 transition-opacity z-50 whitespace-nowrap ${
                  createTooltipAlign === "left"
                    ? "left-0"
                    : createTooltipAlign === "right"
                    ? "right-0"
                    : "left-1/2 -translate-x-1/2"
                }`}
              >
                Create a new local user account
                <div
                  className={`absolute ${
                    createTooltipAlign === "left"
                      ? "left-4"
                      : createTooltipAlign === "right"
                      ? "right-4"
                      : "left-1/2 -translate-x-1/2"
                  } top-0 -translate-y-1/2 rotate-45 border-4 border-transparent border-b-gray-900`}
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Create user inline form */}
      {showCreate && createApiPath && (
        <form onSubmit={handleCreate} className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-semibold text-gray-700">Create Local User</h4>
            <button type="button" onClick={resetCreateForm} className="text-gray-400 hover:text-gray-600">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {createError && (
            <div className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">
              {createError}
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Full Name *</label>
              <input
                type="text"
                value={createForm.full_name}
                onChange={(e) => setCreateForm({ ...createForm, full_name: e.target.value })}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Email *</label>
              <input
                type="email"
                value={createForm.email}
                onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Password *</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={createForm.password}
                  onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 pr-9 text-sm"
                  placeholder="Min. 8 characters"
                  minLength={8}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:text-gray-600"
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
                    </svg>
                  ) : (
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
              <select
                value={createForm.role_name}
                onChange={(e) => setCreateForm({ ...createForm, role_name: e.target.value })}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">-- Default --</option>
                {assignableRoles.map((r) => (
                  <option key={r.id} value={r.name}>
                    {r.name}
                  </option>
                ))}
              </select>
            </div>
            {showOrg && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Organization</label>
                <select
                  value={createForm.org_id}
                  onChange={(e) => {
                    const newOrgId = e.target.value;
                    setCreateForm((prev) => ({
                      ...prev,
                      org_id: newOrgId,
                      team_id:
                        prev.team_id &&
                        teams.some(
                          (t) => t.id === prev.team_id && t.org_id === newOrgId,
                        )
                          ? prev.team_id
                          : "",
                    }));
                  }}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="">-- Select --</option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {showTeam && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Team</label>
                <select
                  value={createForm.team_id}
                  onChange={(e) => setCreateForm({ ...createForm, team_id: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="">-- None --</option>
                  {teams
                    .filter((t) => !showOrg || t.org_id === createForm.org_id)
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                </select>
              </div>
            )}
          </div>

          <div className="mt-3 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={resetCreateForm}
              className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating}
              className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {creating ? "Creating..." : "Create User"}
            </button>
          </div>
        </form>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Auth</th>
              {showOrg && <th className="px-4 py-3">Org</th>}
              {showTeam && <th className="px-4 py-3">Team</th>}
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {loading ? (
              <tr>
                <td
                  colSpan={colCount}
                  className="px-4 py-8 text-center text-gray-400"
                >
                  Loading...
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td
                  colSpan={colCount}
                  className="px-4 py-8 text-center text-gray-400"
                >
                  No users found
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {u.full_name}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{u.email}</td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
                      {roleName(u.role_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        u.auth_method === "sso"
                          ? "bg-blue-100 text-blue-700"
                          : u.auth_method === "local"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {u.auth_method === "sso" ? "SSO" : u.auth_method === "local" ? "Local" : "Unknown"}
                    </span>
                  </td>
                  {showOrg && (
                    <td className="px-4 py-3 text-gray-600">
                      {orgName(u.org_id)}
                    </td>
                  )}
                  {showTeam && (
                    <td className="px-4 py-3 text-gray-600">
                      {teamName(u.team_id)}
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <button
                      onClick={() => toggleUserActive(u)}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                        u.is_active ? "bg-green-500" : "bg-gray-300"
                      }`}
                      title={u.is_active ? "Deactivate" : "Activate"}
                    >
                      <span
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                          u.is_active ? "translate-x-4" : "translate-x-0"
                        }`}
                      />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => openEdit(u)}
                      className="group relative inline-flex items-center justify-center rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                      aria-label="Edit user"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                      </svg>
                      <span className="pointer-events-none absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-800 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                        Edit
                      </span>
                    </button>
                    {deleteApiPrefix && (
                      <button
                        onClick={() => deleteUser(u)}
                        disabled={isProtected(u)}
                        className="group relative ml-1 inline-flex items-center justify-center rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                        aria-label="Delete user"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        <span className="pointer-events-none absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-800 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                          {isProtected(u) ? "Admins can't be deleted" : "Delete"}
                        </span>
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center gap-2">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-gray-600">
            Page {page + 1} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}

      {/* Edit modal */}
      {editUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              Edit User
            </h3>

            <div className="space-y-3">
              {/* Full name */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Full Name
                </label>
                <input
                  type="text"
                  value={editForm.full_name ?? ""}
                  onChange={(e) =>
                    setEditForm({ ...editForm, full_name: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              {/* Email */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Email
                </label>
                <input
                  type="email"
                  value={editForm.email ?? ""}
                  onChange={(e) =>
                    setEditForm({ ...editForm, email: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              {/* Role */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Role
                </label>
                <select
                  value={editForm.role_name ?? ""}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      role_name: e.target.value || null,
                    })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="">-- None --</option>
                  {assignableRoles.map((r) => (
                    <option key={r.id} value={r.name}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Organization (platform admin) */}
              {showOrg && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Organization
                  </label>
                  <select
                    value={editForm.org_id ?? ""}
                    onChange={(e) => {
                      const newOrgId = e.target.value || null;
                      setEditForm((prev) => ({
                        ...prev,
                        org_id: newOrgId,
                        team_id:
                          prev.team_id &&
                          teams.some(
                            (t) => t.id === prev.team_id && t.org_id === newOrgId,
                          )
                            ? prev.team_id
                            : null,
                      }));
                    }}
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  >
                    <option value="">-- None --</option>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Team (org admin) */}
              {showTeam && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Team
                  </label>
                  <select
                    value={editForm.team_id ?? ""}
                    onChange={(e) =>
                      setEditForm({
                        ...editForm,
                        team_id: e.target.value || null,
                      })
                    }
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  >
                    <option value="">-- None --</option>
                    {teams
                      .filter((t) => !showOrg || t.org_id === editForm.org_id)
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                  </select>
                </div>
              )}

              {/* Active toggle + Superuser */}
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <button
                    type="button"
                    onClick={() =>
                      setEditForm({
                        ...editForm,
                        is_active: !editForm.is_active,
                      })
                    }
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                      editForm.is_active ? "bg-green-500" : "bg-gray-300"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                        editForm.is_active ? "translate-x-4" : "translate-x-0"
                      }`}
                    />
                  </button>
                  Active
                </label>
              </div>
            </div>

            <div className="mt-5 flex justify-between">
              <div>
                {editUser.auth_method === "local" && (
                  <button
                    onClick={() => {
                      const u = editUser;
                      setEditUser(null);
                      openResetPassword(u);
                    }}
                    className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100"
                  >
                    Reset Password
                  </button>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setEditUser(null)}
                  className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={saveEdit}
                  disabled={saving}
                  className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Reset password modal */}
      {resetUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-1 text-lg font-semibold text-gray-900">
              Reset Password
            </h3>
            <p className="mb-4 text-sm text-gray-500">
              Set a new password for <span className="font-medium text-gray-700">{resetUser.email}</span>
            </p>

            {resetSuccess ? (
              <div className="space-y-4">
                <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
                  Password has been reset successfully. The user can now sign in with the new password.
                </div>
                <div className="flex justify-end">
                  <button
                    onClick={() => setResetUser(null)}
                    className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {resetError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                    {resetError}
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    New Password
                  </label>
                  <div className="relative">
                    <input
                      type={showResetPassword ? "text" : "password"}
                      value={resetPassword}
                      onChange={(e) => setResetPassword(e.target.value)}
                      className="w-full rounded border border-gray-300 px-3 py-2 pr-10 text-sm"
                      placeholder="Min. 8 characters"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowResetPassword((v) => !v)}
                      className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                      tabIndex={-1}
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        {showResetPassword ? (
                          <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12c1.292 4.338 5.31 7.5 10.066 7.5.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                        ) : (
                          <>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          </>
                        )}
                      </svg>
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Confirm New Password
                  </label>
                  <div className="relative">
                    <input
                      type={showResetPassword ? "text" : "password"}
                      value={resetConfirm}
                      onChange={(e) => setResetConfirm(e.target.value)}
                      className="w-full rounded border border-gray-300 px-3 py-2 pr-10 text-sm"
                      placeholder="Re-enter password"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowResetPassword((v) => !v)}
                      className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                      tabIndex={-1}
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        {showResetPassword ? (
                          <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12c1.292 4.338 5.31 7.5 10.066 7.5.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                        ) : (
                          <>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          </>
                        )}
                      </svg>
                    </button>
                  </div>
                </div>

                <div className="mt-4 flex justify-end gap-2">
                  <button
                    onClick={() => setResetUser(null)}
                    className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={submitResetPassword}
                    disabled={resetting || !resetPassword}
                    className="rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                  >
                    {resetting ? "Resetting..." : "Reset Password"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
