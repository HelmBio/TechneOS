"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  apiPut,
  type Role,
  type Org,
  type PaginatedResponse,
  type ComputeBackend,
  type ComputeArtifact,
} from "@/lib/api";
import LLMProvidersPanel from "@/components/llm-providers-panel";
import BucketsPanel from "@/components/buckets-panel";
import ComputeBackendsPanel from "@/components/compute-backends-panel";
import ComputeArtifactsPanel from "@/components/compute-artifacts-panel";

/* ── Reusable icon SVGs ──────────────────────────────────── */

const PlusIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
  </svg>
);

const CloseIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
  </svg>
);

const EditIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
  </svg>
);

const ChevronIcon = ({ open }: { open: boolean }) => (
  <svg
    className={`h-5 w-5 shrink-0 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
    fill="none" viewBox="0 0 24 24" stroke="currentColor"
  >
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
  </svg>
);

type Section = "roles" | "organizations" | "llm-providers" | "buckets" | "compute-backends" | "compute-artifacts";

const STORAGE_KEY = "admin-config-expanded";

function loadExpanded(): Set<Section> {
  if (typeof window === "undefined") return new Set(["roles"]);
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw) as Section[]);
  } catch { /* ignore */ }
  return new Set(["roles"]);
}

function saveExpanded(sections: Set<Section>) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...sections]));
  } catch { /* ignore */ }
}

const CountBadge = ({ count }: { count: number }) => (
  <span className="ml-2 inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
    {count}
  </span>
);

export default function AdminConfigPage() {
  const [expandedSections, setExpandedSections] = useState<Set<Section>>(loadExpanded);

  // --- Roles state ---
  const [roles, setRoles] = useState<Role[]>([]);
  const [rolesLoading, setRolesLoading] = useState(true);
  const [showRoleForm, setShowRoleForm] = useState(false);
  const [roleForm, setRoleForm] = useState({
    name: "",
    description: "",
    permissions: "",
  });
  const [roleError, setRoleError] = useState("");
  const [roleSaving, setRoleSaving] = useState(false);

  // Role edit modal
  const [editRole, setEditRole] = useState<Role | null>(null);
  const [editRoleForm, setEditRoleForm] = useState({
    description: "",
    permissions: "",
    is_active: true,
  });
  const [editRoleSaving, setEditRoleSaving] = useState(false);
  const [editRoleError, setEditRoleError] = useState("");

  // --- Orgs state ---
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgsLoading, setOrgsLoading] = useState(true);
  const [showOrgForm, setShowOrgForm] = useState(false);
  const [orgForm, setOrgForm] = useState({
    name: "",
    slug: "",
    description: "",
  });
  const [orgError, setOrgError] = useState("");
  const [orgSaving, setOrgSaving] = useState(false);

  // Org edit modal
  const [editOrg, setEditOrg] = useState<Org | null>(null);
  const [editOrgForm, setEditOrgForm] = useState({
    name: "",
    description: "",
    is_active: true,
  });
  const [editOrgSaving, setEditOrgSaving] = useState(false);
  const [editOrgError, setEditOrgError] = useState("");

  // --- LLM Providers create form (controlled) ---
  const [showLLMForm, setShowLLMForm] = useState(false);
  const [llmCount, setLlmCount] = useState(0);

  // --- Buckets create form (controlled) ---
  const [showBucketForm, setShowBucketForm] = useState(false);
  const [bucketCount, setBucketCount] = useState(0);

  // --- Compute backends ---
  const [computeBackendCount, setComputeBackendCount] = useState(0);

  // --- Compute artifacts ---
  const [computeArtifactCount, setComputeArtifactCount] = useState(0);

  // --- Fetch ---

  const fetchRoles = useCallback(async () => {
    try {
      const data = await apiGet<Role[]>("/api/v1/admin/roles");
      setRoles(data);
    } catch (e) {
      console.error(e);
    } finally {
      setRolesLoading(false);
    }
  }, []);

  const fetchOrgs = useCallback(async () => {
    try {
      const data = await apiGet<PaginatedResponse<Org>>("/api/v1/admin/orgs");
      setOrgs(data.items);
    } catch (e) {
      console.error(e);
    } finally {
      setOrgsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRoles();
    fetchOrgs();
    // Fetch LLM provider count eagerly so the badge is correct even when
    // the accordion is collapsed and LLMProvidersPanel is not mounted.
    apiGet<PaginatedResponse<unknown>>("/api/v1/admin/llm-providers")
      .then((d) => setLlmCount(d.total ?? d.items.length))
      .catch(console.error);
    // Fetch bucket count eagerly for the badge.
    apiGet<PaginatedResponse<unknown>>("/api/v1/admin/buckets")
      .then((d) => setBucketCount(d.total ?? d.items.length))
      .catch(console.error);
    // Fetch compute backend count eagerly for the badge. This endpoint
    // returns a plain array (not a PaginatedResponse).
    apiGet<ComputeBackend[]>("/api/v1/compute-backends?enabled_only=false")
      .then((d) => setComputeBackendCount(d.length))
      .catch(console.error);
    // Fetch compute artifact count eagerly for the badge (plain array).
    apiGet<ComputeArtifact[]>("/api/v1/compute-artifacts")
      .then((d) => setComputeArtifactCount(d.length))
      .catch(console.error);
  }, [fetchRoles, fetchOrgs]);

  // --- Create role ---

  const handleCreateRole = async (e: React.FormEvent) => {
    e.preventDefault();
    setRoleError("");
    setRoleSaving(true);
    try {
      const permissions = roleForm.permissions
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
      await apiPost("/api/v1/admin/roles", {
        name: roleForm.name,
        description: roleForm.description || null,
        permissions,
      });
      setRoleForm({ name: "", description: "", permissions: "" });
      setShowRoleForm(false);
      await fetchRoles();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create role";
      setRoleError(msg);
    } finally {
      setRoleSaving(false);
    }
  };

  // --- Edit role ---

  const openEditRole = (role: Role) => {
    setEditRole(role);
    setEditRoleForm({
      description: role.description || "",
      permissions: role.permissions.join(", "),
      is_active: role.is_active,
    });
    setEditRoleError("");
  };

  const saveEditRole = async () => {
    if (!editRole) return;
    setEditRoleSaving(true);
    setEditRoleError("");
    try {
      const permissions = editRoleForm.permissions
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
      await apiPut(`/api/v1/admin/roles/${editRole.id}`, {
        description: editRoleForm.description || null,
        permissions,
        is_active: editRoleForm.is_active,
      });
      setEditRole(null);
      await fetchRoles();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to update role";
      setEditRoleError(msg);
    } finally {
      setEditRoleSaving(false);
    }
  };

  const toggleRoleActive = async (role: Role) => {
    try {
      await apiPut(`/api/v1/admin/roles/${role.id}`, {
        is_active: !role.is_active,
      });
      await fetchRoles();
    } catch (e) {
      console.error("Failed to toggle role status", e);
    }
  };

  // --- Create org ---

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    setOrgError("");
    setOrgSaving(true);
    try {
      await apiPost("/api/v1/admin/orgs", {
        name: orgForm.name,
        slug: orgForm.slug,
        description: orgForm.description || null,
        settings: {},
      });
      setOrgForm({ name: "", slug: "", description: "" });
      setShowOrgForm(false);
      await fetchOrgs();
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to create organization";
      setOrgError(msg);
    } finally {
      setOrgSaving(false);
    }
  };

  // --- Edit org ---

  const openEditOrg = (org: Org) => {
    setEditOrg(org);
    setEditOrgForm({
      name: org.name,
      description: org.description || "",
      is_active: org.is_active,
    });
    setEditOrgError("");
  };

  const saveEditOrg = async () => {
    if (!editOrg) return;
    setEditOrgSaving(true);
    setEditOrgError("");
    try {
      await apiPut(`/api/v1/admin/orgs/${editOrg.id}`, {
        name: editOrgForm.name,
        description: editOrgForm.description || null,
        is_active: editOrgForm.is_active,
      });
      setEditOrg(null);
      await fetchOrgs();
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to update organization";
      setEditOrgError(msg);
    } finally {
      setEditOrgSaving(false);
    }
  };

  const toggleOrgActive = async (org: Org) => {
    try {
      await apiPut(`/api/v1/admin/orgs/${org.id}`, {
        is_active: !org.is_active,
      });
      await fetchOrgs();
    } catch (e) {
      console.error("Failed to toggle org status", e);
    }
  };

  // Auto-generate slug from org name
  const handleOrgNameChange = (name: string) => {
    setOrgForm((prev) => ({
      ...prev,
      name,
      slug: prev.slug === autoSlug(prev.name) ? autoSlug(name) : prev.slug,
    }));
  };

  const toggleSection = (key: Section) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      saveExpanded(next);
      return next;
    });
  };

  return (
    <div className="space-y-2">
      {/* ── Roles ────────────────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("roles")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Roles<CountBadge count={roles.length} /></h2>
              <p className="text-sm text-gray-500">RBAC roles with associated permissions</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            {expandedSections.has("roles") && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowRoleForm((v) => !v);
                  setRoleError("");
                }}
                title={showRoleForm ? "Cancel new role" : "Add role"}
                className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                {showRoleForm ? <CloseIcon /> : <PlusIcon />}
              </button>
            )}
            <button onClick={() => toggleSection("roles")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("roles")} />
            </button>
          </div>
        </div>
        {expandedSections.has("roles") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">

        {/* Create role form */}
        {showRoleForm && (
          <form
            onSubmit={handleCreateRole}
            className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. data_scientist"
                  pattern="^[a-z0-9_]+$"
                  title="Lowercase letters, numbers, and underscores only"
                  value={roleForm.name}
                  onChange={(e) =>
                    setRoleForm({ ...roleForm, name: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Description
                </label>
                <input
                  type="text"
                  placeholder="Optional description"
                  value={roleForm.description}
                  onChange={(e) =>
                    setRoleForm({ ...roleForm, description: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Permissions
                </label>
                <input
                  type="text"
                  placeholder="read, write, admin (comma-separated)"
                  value={roleForm.permissions}
                  onChange={(e) =>
                    setRoleForm({ ...roleForm, permissions: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            {roleError && (
              <p className="mt-2 text-sm text-red-600">{roleError}</p>
            )}
            <div className="mt-3">
              <button
                type="submit"
                disabled={roleSaving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {roleSaving ? "Creating..." : "Create Role"}
              </button>
            </div>
          </form>
        )}

        {/* Roles table */}
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Permissions</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rolesLoading ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-gray-400"
                  >
                    Loading roles...
                  </td>
                </tr>
              ) : roles.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-gray-400"
                  >
                    No roles defined
                  </td>
                </tr>
              ) : (
                roles.map((role) => (
                  <tr key={role.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {role.name}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {role.description || "-"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {role.permissions.length > 0 ? (
                          role.permissions.map((p) => (
                            <span
                              key={p}
                              className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700"
                            >
                              {p}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-gray-400">none</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleRoleActive(role)}
                        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                          role.is_active ? "bg-green-500" : "bg-gray-300"
                        }`}
                        title={role.is_active ? "Deactivate" : "Activate"}
                      >
                        <span
                          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                            role.is_active ? "translate-x-4" : "translate-x-0"
                          }`}
                        />
                      </button>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-400">
                      {role.id.slice(0, 8)}...
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEditRole(role)}
                        title="Edit"
                        className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                      >
                        <EditIcon />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
          </div>
        )}
      </div>

      {/* ── Organizations ────────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("organizations")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Organizations<CountBadge count={orgs.length} /></h2>
              <p className="text-sm text-gray-500">Top-level tenants for multi-org isolation</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            {expandedSections.has("organizations") && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowOrgForm((v) => !v);
                  setOrgError("");
                }}
                title={showOrgForm ? "Cancel new organization" : "Add organization"}
                className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                {showOrgForm ? <CloseIcon /> : <PlusIcon />}
              </button>
            )}
            <button onClick={() => toggleSection("organizations")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("organizations")} />
            </button>
          </div>
        </div>
        {expandedSections.has("organizations") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">

        {/* Create org form */}
        {showOrgForm && (
          <form
            onSubmit={handleCreateOrg}
            className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Pharma"
                  value={orgForm.name}
                  onChange={(e) => handleOrgNameChange(e.target.value)}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Slug <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="acme-pharma"
                  pattern="^[a-z0-9-]+$"
                  title="Lowercase letters, numbers, and hyphens only"
                  value={orgForm.slug}
                  onChange={(e) =>
                    setOrgForm({ ...orgForm, slug: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Description
                </label>
                <input
                  type="text"
                  placeholder="Optional description"
                  value={orgForm.description}
                  onChange={(e) =>
                    setOrgForm({ ...orgForm, description: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            {orgError && (
              <p className="mt-2 text-sm text-red-600">{orgError}</p>
            )}
            <div className="mt-3">
              <button
                type="submit"
                disabled={orgSaving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {orgSaving ? "Creating..." : "Create Organization"}
              </button>
            </div>
          </form>
        )}

        {/* Orgs table */}
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Slug</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {orgsLoading ? (
                <tr>
                  <td
                    colSpan={7}
                    className="px-4 py-8 text-center text-gray-400"
                  >
                    Loading organizations...
                  </td>
                </tr>
              ) : orgs.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    className="px-4 py-8 text-center text-gray-400"
                  >
                    No organizations defined
                  </td>
                </tr>
              ) : (
                orgs.map((org) => (
                  <tr key={org.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {org.name}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">
                      {org.slug}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {org.description || "-"}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleOrgActive(org)}
                        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                          org.is_active ? "bg-green-500" : "bg-gray-300"
                        }`}
                        title={org.is_active ? "Deactivate" : "Activate"}
                      >
                        <span
                          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                            org.is_active ? "translate-x-4" : "translate-x-0"
                          }`}
                        />
                      </button>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(org.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-400">
                      {org.id.slice(0, 8)}...
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEditOrg(org)}
                        title="Edit"
                        className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                      >
                        <EditIcon />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
          </div>
        )}
      </div>

      {/* ── LLM Providers ────────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("llm-providers")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">LLM Providers<CountBadge count={llmCount} /></h2>
              <p className="text-sm text-gray-500">Configured model providers for AI agents</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            {expandedSections.has("llm-providers") && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowLLMForm((v) => !v);
                }}
                title={showLLMForm ? "Cancel new provider" : "Add provider"}
                className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                {showLLMForm ? <CloseIcon /> : <PlusIcon />}
              </button>
            )}
            <button onClick={() => toggleSection("llm-providers")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("llm-providers")} />
            </button>
          </div>
        </div>
        {expandedSections.has("llm-providers") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">
            <LLMProvidersPanel
              apiBasePath="/api/v1/admin/llm-providers"
              showOrg
              hideHeader
              showCreateForm={showLLMForm}
              onToggleCreateForm={() => setShowLLMForm((v) => !v)}
              onCountChange={setLlmCount}
            />
          </div>
        )}
      </div>

      {/* ── Object Store Buckets ──────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("buckets")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Object Store Buckets<CountBadge count={bucketCount} /></h2>
              <p className="text-sm text-gray-500">Registered S3-compatible storage for dataset transfers</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            {expandedSections.has("buckets") && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowBucketForm((v) => !v);
                }}
                title={showBucketForm ? "Cancel new bucket" : "Add bucket"}
                className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                {showBucketForm ? <CloseIcon /> : <PlusIcon />}
              </button>
            )}
            <button onClick={() => toggleSection("buckets")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("buckets")} />
            </button>
          </div>
        </div>
        {expandedSections.has("buckets") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">
            <BucketsPanel
              apiBasePath="/api/v1/admin/buckets"
              showOrg
              hideHeader
              showCreateForm={showBucketForm}
              onToggleCreateForm={() => setShowBucketForm((v) => !v)}
              onCountChange={setBucketCount}
            />
          </div>
        )}
      </div>

      {/* ── Compute Backends ──────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("compute-backends")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Compute Backends<CountBadge count={computeBackendCount} /></h2>
              <p className="text-sm text-gray-500">Execution backends for tool and pipeline runs</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            <button onClick={() => toggleSection("compute-backends")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("compute-backends")} />
            </button>
          </div>
        </div>
        {expandedSections.has("compute-backends") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">
            <ComputeBackendsPanel
              hideHeader
              onCountChange={setComputeBackendCount}
            />
          </div>
        )}
      </div>

      {/* ── Compute Artifacts ─────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("compute-artifacts")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Compute Artifacts<CountBadge count={computeArtifactCount} /></h2>
              <p className="text-sm text-gray-500">Inventory of built &amp; published wheels and docker images</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            <button onClick={() => toggleSection("compute-artifacts")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("compute-artifacts")} />
            </button>
          </div>
        </div>
        {expandedSections.has("compute-artifacts") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">
            <ComputeArtifactsPanel
              hideHeader
              onCountChange={setComputeArtifactCount}
            />
          </div>
        )}
      </div>

      {/* ── Edit Role Modal ──────────────────────────────── */}
      {editRole && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              Edit Role: <span className="font-mono">{editRole.name}</span>
            </h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Description
                </label>
                <input
                  type="text"
                  value={editRoleForm.description}
                  onChange={(e) =>
                    setEditRoleForm({
                      ...editRoleForm,
                      description: e.target.value,
                    })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Permissions (comma-separated)
                </label>
                <input
                  type="text"
                  value={editRoleForm.permissions}
                  onChange={(e) =>
                    setEditRoleForm({
                      ...editRoleForm,
                      permissions: e.target.value,
                    })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <button
                  type="button"
                  onClick={() =>
                    setEditRoleForm({
                      ...editRoleForm,
                      is_active: !editRoleForm.is_active,
                    })
                  }
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                    editRoleForm.is_active ? "bg-green-500" : "bg-gray-300"
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                      editRoleForm.is_active ? "translate-x-4" : "translate-x-0"
                    }`}
                  />
                </button>
                Active
              </label>
            </div>
            {editRoleError && (
              <p className="mt-2 text-sm text-red-600">{editRoleError}</p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setEditRole(null)}
                className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={saveEditRole}
                disabled={editRoleSaving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {editRoleSaving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit Org Modal ───────────────────────────────── */}
      {editOrg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              Edit Organization
            </h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Name
                </label>
                <input
                  type="text"
                  value={editOrgForm.name}
                  onChange={(e) =>
                    setEditOrgForm({ ...editOrgForm, name: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Description
                </label>
                <input
                  type="text"
                  value={editOrgForm.description}
                  onChange={(e) =>
                    setEditOrgForm({
                      ...editOrgForm,
                      description: e.target.value,
                    })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <button
                  type="button"
                  onClick={() =>
                    setEditOrgForm({
                      ...editOrgForm,
                      is_active: !editOrgForm.is_active,
                    })
                  }
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                    editOrgForm.is_active ? "bg-green-500" : "bg-gray-300"
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                      editOrgForm.is_active ? "translate-x-4" : "translate-x-0"
                    }`}
                  />
                </button>
                Active
              </label>
            </div>
            {editOrgError && (
              <p className="mt-2 text-sm text-red-600">{editOrgError}</p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setEditOrg(null)}
                className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={saveEditOrg}
                disabled={editOrgSaving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {editOrgSaving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function autoSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
