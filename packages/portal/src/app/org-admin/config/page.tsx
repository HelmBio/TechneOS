"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  apiGet,
  apiPost,
  apiPut,
  type PaginatedResponse,
  type Team,
} from "@/lib/api";
import LLMProvidersPanel from "@/components/llm-providers-panel";
import BucketsPanel from "@/components/buckets-panel";

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

const CountBadge = ({ count }: { count: number }) => (
  <span className="ml-2 inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
    {count}
  </span>
);

interface TeamForm {
  name: string;
  description: string;
  is_active: boolean;
}

type Section = "teams" | "llm-providers" | "buckets";

const STORAGE_KEY = "org-admin-config-expanded";

function loadExpanded(): Set<Section> {
  if (typeof window === "undefined") return new Set(["teams"]);
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw) as Section[]);
  } catch { /* ignore */ }
  return new Set(["teams"]);
}

function saveExpanded(sections: Set<Section>) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...sections]));
  } catch { /* ignore */ }
}

export default function OrgAdminConfigPage() {
  const { user } = useAuth();
  const [expandedSections, setExpandedSections] = useState<Set<Section>>(loadExpanded);

  const [teams, setTeams] = useState<Team[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<TeamForm>({
    name: "",
    description: "",
    is_active: true,
  });
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  // Edit modal
  const [editTeam, setEditTeam] = useState<Team | null>(null);
  const [editForm, setEditForm] = useState<TeamForm>({
    name: "",
    description: "",
    is_active: true,
  });
  const [saving, setSaving] = useState(false);

  // LLM Providers create form (controlled)
  const [showLLMForm, setShowLLMForm] = useState(false);
  const [llmCount, setLlmCount] = useState(0);

  // Buckets create form (controlled)
  const [showBucketForm, setShowBucketForm] = useState(false);
  const [bucketCount, setBucketCount] = useState(0);

  const orgId = user?.org_id;

  const fetchTeams = useCallback(async () => {
    if (!orgId) return;
    setLoading(true);
    try {
      const data = await apiGet<PaginatedResponse<Team>>(
        `/api/v1/orgs/${orgId}/teams`,
        { limit: "200" },
      );
      setTeams(data.items);
      setTotal(data.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    fetchTeams();
    // Fetch LLM provider count eagerly so the badge is correct even when
    // the accordion is collapsed and LLMProvidersPanel is not mounted.
    if (orgId) {
      apiGet<PaginatedResponse<unknown>>(`/api/v1/orgs/${orgId}/llm-providers`)
        .then((d) => setLlmCount(d.total ?? d.items.length))
        .catch(console.error);
      // Fetch bucket count eagerly for the badge.
      apiGet<PaginatedResponse<unknown>>(`/api/v1/orgs/${orgId}/buckets`)
        .then((d) => setBucketCount(d.total ?? d.items.length))
        .catch(console.error);
    }
  }, [fetchTeams, orgId]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orgId) return;
    setCreateError("");
    setCreating(true);
    try {
      await apiPost(`/api/v1/orgs/${orgId}/teams?org_id=${orgId}`, {
        name: createForm.name,
        description: createForm.description || null,
      });
      setCreateForm({ name: "", description: "", is_active: true });
      setShowCreate(false);
      await fetchTeams();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create team";
      setCreateError(msg);
    } finally {
      setCreating(false);
    }
  };

  const openEdit = (t: Team) => {
    setEditTeam(t);
    setEditForm({ name: t.name, description: t.description || "", is_active: t.is_active });
  };

  const saveEdit = async () => {
    if (!editTeam || !orgId) return;
    setSaving(true);
    try {
      await apiPut(`/api/v1/orgs/${orgId}/teams/${editTeam.id}?org_id=${orgId}`, {
        name: editForm.name,
        description: editForm.description || null,
        is_active: editForm.is_active,
      });
      setEditTeam(null);
      fetchTeams();
    } catch (e) {
      console.error(e);
      alert("Failed to update team");
    } finally {
      setSaving(false);
    }
  };

  const toggleTeamActive = async (t: Team) => {
    if (!orgId) return;
    try {
      await apiPut(`/api/v1/orgs/${orgId}/teams/${t.id}?org_id=${orgId}`, {
        is_active: !t.is_active,
      });
      await fetchTeams();
    } catch (e) {
      console.error("Failed to toggle team status", e);
    }
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

  if (!orgId) {
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-6 text-center">
        <p className="text-yellow-800">
          You are not assigned to an organization.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* ── Teams ─────────────────────────────────────────── */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-5 py-4">
          <button
            onClick={() => toggleSection("teams")}
            className="flex flex-1 items-center justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Teams<CountBadge count={total} /></h2>
              <p className="text-sm text-gray-500">Teams in your organization</p>
            </div>
          </button>
          <div className="flex items-center gap-1 ml-3">
            {expandedSections.has("teams") && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowCreate((v) => !v);
                  setCreateError("");
                }}
                title={showCreate ? "Cancel new team" : "Add team"}
                className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                {showCreate ? <CloseIcon /> : <PlusIcon />}
              </button>
            )}
            <button onClick={() => toggleSection("teams")} className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100">
              <ChevronIcon open={expandedSections.has("teams")} />
            </button>
          </div>
        </div>
        {expandedSections.has("teams") && (
          <div className="border-t border-gray-200 px-5 pb-5 pt-4">

            {/* Create form */}
            {showCreate && (
              <form
                onSubmit={handleCreate}
                className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4"
              >
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-700">
                      Name <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. Computational Chemistry"
                      value={createForm.name}
                      onChange={(e) =>
                        setCreateForm({ ...createForm, name: e.target.value })
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
                      value={createForm.description}
                      onChange={(e) =>
                        setCreateForm({ ...createForm, description: e.target.value })
                      }
                      className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                </div>
                {createError && (
                  <p className="mt-2 text-sm text-red-600">{createError}</p>
                )}
                <div className="mt-3">
                  <button
                    type="submit"
                    disabled={creating}
                    className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {creating ? "Creating..." : "Create Team"}
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
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Created</th>
                    <th className="px-4 py-3">ID</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {loading ? (
                    <tr>
                      <td
                        colSpan={6}
                        className="px-4 py-8 text-center text-gray-400"
                      >
                        Loading...
                      </td>
                    </tr>
                  ) : teams.length === 0 ? (
                    <tr>
                      <td
                        colSpan={6}
                        className="px-4 py-8 text-center text-gray-400"
                      >
                        No teams yet. Create one to get started.
                      </td>
                    </tr>
                  ) : (
                    teams.map((t) => (
                      <tr key={t.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-900">
                          {t.name}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {t.description || "-"}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => toggleTeamActive(t)}
                            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                              t.is_active ? "bg-green-500" : "bg-gray-300"
                            }`}
                            title={t.is_active ? "Deactivate" : "Activate"}
                          >
                            <span
                              className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                                t.is_active ? "translate-x-4" : "translate-x-0"
                              }`}
                            />
                          </button>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500">
                          {new Date(t.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-gray-400">
                          {t.id.slice(0, 8)}...
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => openEdit(t)}
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
              apiBasePath={`/api/v1/orgs/${orgId}/llm-providers`}
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
              apiBasePath={`/api/v1/orgs/${orgId}/buckets`}
              hideHeader
              showCreateForm={showBucketForm}
              onToggleCreateForm={() => setShowBucketForm((v) => !v)}
              onCountChange={setBucketCount}
            />
          </div>
        )}
      </div>

      {/* ── Edit Team Modal ──────────────────────────────── */}
      {editTeam && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              Edit Team
            </h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Name
                </label>
                <input
                  type="text"
                  value={editForm.name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, name: e.target.value })
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
                  value={editForm.description}
                  onChange={(e) =>
                    setEditForm({ ...editForm, description: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
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
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setEditTeam(null)}
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
      )}
    </div>
  );
}
