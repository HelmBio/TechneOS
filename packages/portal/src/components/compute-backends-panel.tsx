"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch, type ComputeBackend } from "@/lib/api";

interface ComputeBackendsPanelProps {
  /** API path prefix — controls which endpoint is hit. */
  apiBasePath?: string;
  /** When true, the internal header is hidden (accordion provides it). */
  hideHeader?: boolean;
  /** Called when the backend count changes. */
  onCountChange?: (count: number) => void;
}

const STATUS_BADGE: Record<string, string> = {
  enabled: "bg-green-100 text-green-800",
  disabled: "bg-gray-100 text-gray-600",
  provisioning: "bg-amber-100 text-amber-800",
};

function statusBadgeClass(status: string): string {
  return STATUS_BADGE[status] ?? "bg-gray-100 text-gray-600";
}

/** One-line summary of the capabilities JSON, e.g. "gpu · 256 GB". */
function capabilitiesSummary(capabilities: Record<string, unknown>): string {
  const parts: string[] = [];
  if (capabilities.gpu === true) parts.push("gpu");
  const mem = capabilities.max_memory_gb;
  if (typeof mem === "number") parts.push(`${mem} GB`);
  return parts.length ? parts.join(" · ") : "—";
}

export default function ComputeBackendsPanel({
  apiBasePath = "/api/v1/compute-backends",
  hideHeader = false,
  onCountChange,
}: ComputeBackendsPanelProps) {
  const [backends, setBackends] = useState<ComputeBackend[]>([]);
  const [loading, setLoading] = useState(true);

  // --- Edit modal ---
  const [editItem, setEditItem] = useState<ComputeBackend | null>(null);
  const [editForm, setEditForm] = useState({
    display_name: "",
    description: "",
    status: "disabled",
    config: "{}",
    capabilities: "{}",
  });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");

  // --- Fetch (plain array, includes disabled backends) ---
  const fetchBackends = useCallback(async () => {
    try {
      const data = await apiGet<ComputeBackend[]>(
        `${apiBasePath}?enabled_only=false`,
      );
      setBackends(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [apiBasePath]);

  useEffect(() => {
    fetchBackends();
  }, [fetchBackends]);

  useEffect(() => {
    onCountChange?.(backends.length);
  }, [backends.length, onCountChange]);

  // --- Quick enable/disable toggle ---
  const toggleStatus = async (b: ComputeBackend) => {
    const next = b.status === "enabled" ? "disabled" : "enabled";
    try {
      await apiPatch(`${apiBasePath}/${b.name}`, { status: next });
      await fetchBackends();
    } catch (e) {
      console.error("Failed to toggle backend status", e);
    }
  };

  // --- Edit ---
  const openEdit = (b: ComputeBackend) => {
    setEditItem(b);
    setEditError("");
    setEditForm({
      display_name: b.display_name,
      description: b.description ?? "",
      status: b.status,
      config: JSON.stringify(b.config ?? {}, null, 2),
      capabilities: JSON.stringify(b.capabilities ?? {}, null, 2),
    });
  };

  const saveEdit = async () => {
    if (!editItem) return;
    setEditError("");

    let config: Record<string, unknown>;
    let capabilities: Record<string, unknown>;
    try {
      config = JSON.parse(editForm.config || "{}");
    } catch {
      setEditError("Config is not valid JSON");
      return;
    }
    try {
      capabilities = JSON.parse(editForm.capabilities || "{}");
    } catch {
      setEditError("Capabilities is not valid JSON");
      return;
    }

    setEditSaving(true);
    try {
      await apiPatch(`${apiBasePath}/${editItem.name}`, {
        display_name: editForm.display_name,
        description: editForm.description || null,
        status: editForm.status,
        config,
        capabilities,
      });
      setEditItem(null);
      await fetchBackends();
    } catch (e) {
      setEditError(e instanceof Error ? e.message : "Failed to save backend");
    } finally {
      setEditSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <section>
        {!hideHeader && (
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Compute Backends
            </h2>
            <p className="text-sm text-gray-500">
              Execution backends for tool and pipeline runs
            </p>
          </div>
        )}

        {/* ── Table ────────────────────────────────────────── */}
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Backend</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Capabilities</th>
                <th className="px-4 py-3">Updated</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                    Loading backends...
                  </td>
                </tr>
              ) : backends.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                    No compute backends registered
                  </td>
                </tr>
              ) : (
                backends.map((b) => (
                  <tr key={b.name} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900">
                        {b.display_name}
                      </div>
                      <div className="font-mono text-xs text-gray-500">
                        {b.name}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">
                      {b.backend_type}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => toggleStatus(b)}
                          disabled={b.status === "provisioning"}
                          className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
                            b.status === "enabled" ? "bg-green-500" : "bg-gray-300"
                          }`}
                          title={b.status === "enabled" ? "Disable" : "Enable"}
                        >
                          <span
                            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                              b.status === "enabled" ? "translate-x-4" : "translate-x-0"
                            }`}
                          />
                        </button>
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(b.status)}`}
                        >
                          {b.status}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {capabilitiesSummary(b.capabilities)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {new Date(b.updated_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openEdit(b)}
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
              Edit Backend: <span className="font-mono">{editItem.name}</span>
            </h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Display Name
                </label>
                <input
                  type="text"
                  value={editForm.display_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, display_name: e.target.value })
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
                  Status
                </label>
                <select
                  value={editForm.status}
                  onChange={(e) =>
                    setEditForm({ ...editForm, status: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="enabled">enabled</option>
                  <option value="disabled">disabled</option>
                  <option value="provisioning">provisioning</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Config (JSON)
                </label>
                <textarea
                  rows={5}
                  value={editForm.config}
                  onChange={(e) =>
                    setEditForm({ ...editForm, config: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-xs"
                  spellCheck={false}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">
                  Capabilities (JSON)
                </label>
                <textarea
                  rows={4}
                  value={editForm.capabilities}
                  onChange={(e) =>
                    setEditForm({ ...editForm, capabilities: e.target.value })
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-xs"
                  spellCheck={false}
                />
              </div>
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
