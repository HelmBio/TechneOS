"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  apiPut,
  type LLMProvider,
  type Org,
  type PaginatedResponse,
} from "@/lib/api";

function autoSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

interface LLMProvidersPanelProps {
  /** API path prefix — controls which endpoint is hit. */
  apiBasePath?: string;
  /** Show the Organization column (platform admin cross-org view). */
  showOrg?: boolean;
  /** When true, the internal header is hidden (accordion provides it). */
  hideHeader?: boolean;
  /** Controlled create-form visibility (set by accordion header icon). */
  showCreateForm?: boolean;
  /** Callback to toggle create-form (set by accordion header icon). */
  onToggleCreateForm?: () => void;
  /** Called when the provider count changes. */
  onCountChange?: (count: number) => void;
}

export default function LLMProvidersPanel({
  apiBasePath = "/api/v1/admin/llm-providers",
  showOrg = false,
  hideHeader = false,
  showCreateForm: controlledShowForm,
  onToggleCreateForm,
  onCountChange,
}: LLMProvidersPanelProps) {
  // --- List state ---
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loading, setLoading] = useState(true);

  // --- Orgs (for platform admin org selector) ---
  const [orgs, setOrgs] = useState<Org[]>([]);

  // --- Create form ---
  const [internalShowForm, setInternalShowForm] = useState(false);
  const showForm = controlledShowForm !== undefined ? controlledShowForm : internalShowForm;
  const toggleForm = onToggleCreateForm || (() => setInternalShowForm((v) => !v));

  const [form, setForm] = useState({
    name: "",
    slug: "",
    description: "",
    base_url: "",
    api_key: "",
    default_model: "",
    supported_models: "",
    max_tokens: "",
    is_default: false,
    org_id: "",
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // --- Edit modal ---
  const [editItem, setEditItem] = useState<LLMProvider | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    description: "",
    base_url: "",
    api_key: "",
    default_model: "",
    supported_models: "",
    max_tokens: "",
    is_default: false,
    is_active: true,
  });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");

  // --- Fetch ---
  const fetchProviders = useCallback(async () => {
    try {
      const data = await apiGet<PaginatedResponse<LLMProvider>>(apiBasePath);
      setProviders(data.items);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [apiBasePath]);

  useEffect(() => {
    fetchProviders();
    if (showOrg) {
      apiGet<PaginatedResponse<Org>>("/api/v1/admin/orgs", { limit: "200" })
        .then((d) => setOrgs(d.items))
        .catch(console.error);
    }
  }, [fetchProviders, showOrg]);

  useEffect(() => {
    onCountChange?.(providers.length);
  }, [providers.length, onCountChange]);

  // --- Create ---
  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const supportedModels = form.supported_models
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await apiPost(apiBasePath, {
        name: form.name,
        slug: form.slug,
        description: form.description || null,
        provider_type: "openai_compatible",
        base_url: form.base_url || null,
        api_key: form.api_key || null,
        default_model: form.default_model,
        supported_models: supportedModels,
        max_tokens: form.max_tokens ? parseInt(form.max_tokens, 10) : null,
        is_default: form.is_default,
        ...(showOrg && form.org_id ? { org_id: form.org_id } : {}),
      });
      setForm({
        name: "",
        slug: "",
        description: "",
        base_url: "",
        api_key: "",
        default_model: "",
        supported_models: "",
        max_tokens: "",
        is_default: false,
        org_id: "",
      });
      toggleForm();
      await fetchProviders();
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to create provider";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  // --- Edit ---
  const openEdit = (p: LLMProvider) => {
    setEditItem(p);
    setEditForm({
      name: p.name,
      description: p.description || "",
      base_url: p.base_url || "",
      api_key: "",
      default_model: p.default_model,
      supported_models: p.supported_models.join(", "),
      max_tokens: p.max_tokens?.toString() || "",
      is_default: p.is_default,
      is_active: p.is_active,
    });
    setEditError("");
  };

  const saveEdit = async () => {
    if (!editItem) return;
    setEditSaving(true);
    setEditError("");
    try {
      const supportedModels = editForm.supported_models
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await apiPut(`${apiBasePath}/${editItem.id}`, {
        name: editForm.name,
        description: editForm.description || null,
        base_url: editForm.base_url || null,
        api_key: editForm.api_key || null,
        default_model: editForm.default_model,
        supported_models: supportedModels,
        max_tokens: editForm.max_tokens
          ? parseInt(editForm.max_tokens, 10)
          : null,
        is_default: editForm.is_default,
        is_active: editForm.is_active,
      });
      setEditItem(null);
      await fetchProviders();
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to update provider";
      setEditError(msg);
    } finally {
      setEditSaving(false);
    }
  };

  // --- Toggle active ---
  const toggleActive = async (p: LLMProvider) => {
    try {
      await apiPut(`${apiBasePath}/${p.id}`, {
        is_active: !p.is_active,
      });
      await fetchProviders();
    } catch (e) {
      console.error("Failed to toggle provider status", e);
    }
  };

  // Auto-generate slug from name
  const handleNameChange = (name: string) => {
    setForm((prev) => ({
      ...prev,
      name,
      slug: prev.slug === autoSlug(prev.name) ? autoSlug(name) : prev.slug,
    }));
  };

  return (
    <div className="space-y-6">
      <section>
        {!hideHeader && (
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                LLM Providers
              </h2>
              <p className="text-sm text-gray-500">
                Registered LLM backends for AI agents (OpenAI, Gemini, Azure,
                vLLM, Ollama)
              </p>
            </div>
            <button
              onClick={() => {
                toggleForm();
                setError("");
              }}
              title={showForm ? "Cancel" : "Add provider"}
              className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            >
              {showForm ? (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              )}
            </button>
          </div>
        )}

        {/* ── Create form ──────────────────────────────────── */}
        {showForm && (
          <form
            onSubmit={handleCreate}
            className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {showOrg && (
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">
                    Organization <span className="text-red-500">*</span>
                  </label>
                  <select
                    required
                    value={form.org_id}
                    onChange={(e) =>
                      setForm({ ...form, org_id: e.target.value })
                    }
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="">-- Select organization --</option>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Gemini 2.0 Flash"
                  value={form.name}
                  onChange={(e) => handleNameChange(e.target.value)}
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
                  placeholder="gemini-flash"
                  pattern="^[a-z0-9][a-z0-9._-]*$"
                  title="Lowercase letters, numbers, dots, hyphens, underscores"
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  API Key
                </label>
                <input
                  type="password"
                  placeholder="Paste API key (stored encrypted)"
                  value={form.api_key}
                  onChange={(e) =>
                    setForm({ ...form, api_key: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Base URL
                </label>
                <input
                  type="text"
                  placeholder="https://generativelanguage.googleapis.com/v1beta/openai/"
                  value={form.base_url}
                  onChange={(e) =>
                    setForm({ ...form, base_url: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Default Model <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="gemini-2.0-flash"
                  value={form.default_model}
                  onChange={(e) =>
                    setForm({ ...form, default_model: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Supported Models
                </label>
                <input
                  type="text"
                  placeholder="gemini-2.0-flash, gemini-2.5-pro (comma-separated)"
                  value={form.supported_models}
                  onChange={(e) =>
                    setForm({ ...form, supported_models: e.target.value })
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
                  value={form.description}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">
                  Max Tokens
                </label>
                <input
                  type="number"
                  placeholder="e.g. 8192"
                  value={form.max_tokens}
                  onChange={(e) =>
                    setForm({ ...form, max_tokens: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_default}
                    onChange={(e) =>
                      setForm({ ...form, is_default: e.target.checked })
                    }
                    className="rounded"
                  />
                  Default provider
                </label>
              </div>
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
            <div className="mt-3">
              <button
                type="submit"
                disabled={saving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Creating..." : "Create Provider"}
              </button>
            </div>
          </form>
        )}

        {/* ── Table ────────────────────────────────────────── */}
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Slug</th>
                {showOrg && <th className="px-4 py-3">Organization</th>}
                <th className="px-4 py-3">Default Model</th>
                <th className="px-4 py-3">Base URL</th>
                <th className="px-4 py-3">API Key</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {loading ? (
                <tr>
                  <td
                    colSpan={showOrg ? 9 : 8}
                    className="px-4 py-8 text-center text-gray-400"
                  >
                    Loading providers...
                  </td>
                </tr>
              ) : providers.length === 0 ? (
                <tr>
                  <td
                    colSpan={showOrg ? 9 : 8}
                    className="px-4 py-8 text-center text-gray-400"
                  >
                    No LLM providers registered
                  </td>
                </tr>
              ) : (
                providers.map((p) => (
                  <tr key={p.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {p.name}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">
                      {p.slug}
                    </td>
                    {showOrg && (
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {p.org_name || "\u2014"}
                      </td>
                    )}
                    <td className="px-4 py-3 font-mono text-xs text-gray-700">
                      {p.default_model}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 max-w-48 truncate">
                      {p.base_url || "(default)"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">
                      {p.has_api_key ? "✓ Stored encrypted" : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => toggleActive(p)}
                          className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                            p.is_active ? "bg-green-500" : "bg-gray-300"
                          }`}
                          title={p.is_active ? "Deactivate" : "Activate"}
                        >
                          <span
                            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                              p.is_active ? "translate-x-4" : "translate-x-0"
                            }`}
                          />
                        </button>
                        {p.is_default && (
                          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                            default
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEdit(p)}
                        title="Edit"
                        className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Edit Modal ─────────────────────────────────────── */}
      {editItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              Edit Provider:{" "}
              <span className="font-mono">{editItem.slug}</span>
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
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Base URL
                </label>
                <input
                  type="text"
                  value={editForm.base_url}
                  onChange={(e) =>
                    setEditForm({ ...editForm, base_url: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">
                    API Key (leave blank to keep existing)
                  </label>
                  <input
                    type="password"
                    placeholder="New API key (stored encrypted)"
                    value={editForm.api_key}
                    onChange={(e) =>
                      setEditForm({ ...editForm, api_key: e.target.value })
                    }
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">
                    Default Model
                  </label>
                  <input
                    type="text"
                    value={editForm.default_model}
                    onChange={(e) =>
                      setEditForm({
                        ...editForm,
                        default_model: e.target.value,
                      })
                    }
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm font-mono"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Supported Models (comma-separated)
                </label>
                <input
                  type="text"
                  value={editForm.supported_models}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      supported_models: e.target.value,
                    })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">
                    Max Tokens
                  </label>
                  <input
                    type="number"
                    value={editForm.max_tokens}
                    onChange={(e) =>
                      setEditForm({ ...editForm, max_tokens: e.target.value })
                    }
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
                <div className="flex items-end pb-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={editForm.is_default}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          is_default: e.target.checked,
                        })
                      }
                      className="rounded"
                    />
                    Default provider
                  </label>
                </div>
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
            {editError && (
              <p className="mt-2 text-sm text-red-600">{editError}</p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setEditItem(null)}
                className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={editSaving}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {editSaving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
