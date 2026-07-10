"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPatch, type ComputeArtifact } from "@/lib/api";

interface ComputeArtifactsPanelProps {
  /** API path prefix — controls which endpoint is hit. */
  apiBasePath?: string;
  /** When true, the internal header is hidden (accordion provides it). */
  hideHeader?: boolean;
  /** Called when the artifact count changes. */
  onCountChange?: (count: number) => void;
}

const STATUS_BADGE: Record<string, string> = {
  available: "bg-green-100 text-green-800",
  deprecated: "bg-amber-100 text-amber-800",
  deleted: "bg-gray-100 text-gray-600",
};

const KIND_LABEL: Record<string, string> = {
  wheel: "wheel",
  docker_image: "image",
};

function statusBadgeClass(status: string): string {
  return STATUS_BADGE[status] ?? "bg-gray-100 text-gray-600";
}

export default function ComputeArtifactsPanel({
  apiBasePath = "/api/v1/compute-artifacts",
  hideHeader = false,
  onCountChange,
}: ComputeArtifactsPanelProps) {
  const [artifacts, setArtifacts] = useState<ComputeArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [kindFilter, setKindFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const fetchArtifacts = useCallback(async () => {
    const params = new URLSearchParams();
    if (kindFilter) params.set("kind", kindFilter);
    if (statusFilter) params.set("status", statusFilter);
    const qs = params.toString();
    try {
      const data = await apiGet<ComputeArtifact[]>(
        `${apiBasePath}${qs ? `?${qs}` : ""}`,
      );
      setArtifacts(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [apiBasePath, kindFilter, statusFilter]);

  useEffect(() => {
    fetchArtifacts();
  }, [fetchArtifacts]);

  useEffect(() => {
    onCountChange?.(artifacts.length);
  }, [artifacts.length, onCountChange]);

  // Deprecate ⇄ restore. Deleted artifacts are left as-is (re-publish restores).
  const toggleDeprecated = async (a: ComputeArtifact) => {
    const next = a.status === "available" ? "deprecated" : "available";
    try {
      await apiPatch(`${apiBasePath}/${a.id}`, { status: next });
      await fetchArtifacts();
    } catch (e) {
      console.error("Failed to update artifact status", e);
    }
  };

  const originCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of artifacts) counts[a.origin] = (counts[a.origin] ?? 0) + 1;
    return counts;
  }, [artifacts]);

  return (
    <div className="space-y-4">
      <section>
        {!hideHeader && (
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Compute Artifacts
            </h2>
            <p className="text-sm text-gray-500">
              Inventory of built &amp; published wheels and docker images
            </p>
          </div>
        )}

        {/* ── Filters ──────────────────────────────────────── */}
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-xs"
          >
            <option value="">All kinds</option>
            <option value="wheel">Wheel</option>
            <option value="docker_image">Docker image</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-xs"
          >
            <option value="">All statuses</option>
            <option value="available">Available</option>
            <option value="deprecated">Deprecated</option>
            <option value="deleted">Deleted</option>
          </select>
          <span className="ml-auto text-xs text-gray-400">
            {Object.entries(originCounts)
              .map(([o, n]) => `${o}: ${n}`)
              .join("  ·  ") || "—"}
          </span>
        </div>

        {/* ── Table ────────────────────────────────────────── */}
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3">Artifact</th>
                <th className="px-4 py-3">Kind</th>
                <th className="px-4 py-3">Origin</th>
                <th className="px-4 py-3">Version</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Published</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                    Loading artifacts...
                  </td>
                </tr>
              ) : artifacts.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                    No artifacts recorded yet
                  </td>
                </tr>
              ) : (
                artifacts.map((a) => (
                  <tr key={a.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-gray-900">
                        {a.name}
                      </div>
                      {a.digest && (
                        <div
                          className="max-w-xs truncate font-mono text-[10px] text-gray-400"
                          title={a.digest}
                        >
                          {a.digest}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {KIND_LABEL[a.kind] ?? a.kind}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">
                      {a.origin}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">
                      {a.version}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(a.status)}`}
                      >
                        {a.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {a.published_at
                        ? new Date(a.published_at).toLocaleDateString()
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {a.status !== "deleted" && (
                        <button
                          onClick={() => toggleDeprecated(a)}
                          className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                          title={
                            a.status === "available"
                              ? "Deprecate"
                              : "Mark available"
                          }
                        >
                          {a.status === "available" ? "Deprecate" : "Restore"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
