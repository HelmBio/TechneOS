"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, type Tool, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLabel } from "@/lib/labels";
import { useSubscriptions } from "@/lib/use-subscriptions";
import { FollowIconButton } from "@/components/follow-icon-button";
import { NewResourceButton } from "@/components/new-resource-button";
import { ResourceCard } from "@/components/resource-card";
import { hasPermission } from "@/lib/rbac";
import { TOOL_CATEGORIES } from "@/lib/constants";

const CATEGORIES = ["all", ...TOOL_CATEGORIES];

const TYPE_COLORS: Record<string, string> = {
  container: "bg-indigo-100 text-indigo-700",
  module: "bg-emerald-100 text-emerald-700",
  pypi: "bg-purple-100 text-purple-700",
  api: "bg-cyan-100 text-cyan-700",
};

export default function ToolsPage() {
  const toolsLabel = useLabel("resource.tool.plural");
  const { user, loading: authLoading } = useAuth();
  const [tools, setTools] = useState<Tool[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const { isFollowed, toggle } = useSubscriptions("tool");

  useEffect(() => {
    if (authLoading || !user) return;
    const params: Record<string, string> = { skip: "0", limit: "50" };
    if (search) params.q = search;
    if (category !== "all") params.category = category;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<Tool>>("/api/v1/tools", params);
        const filtered = data.items.filter((t) => t.tool_type !== "human");
        setTools(filtered);
        setTotal(data.total);
      } catch {
        setTools([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, search, category]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user) return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to view tools.</p>;

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{toolsLabel}</h1>
          {total > 0 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {total}
            </span>
          )}
        </div>
        {hasPermission(user.permissions || [], "tool", "create", "*") && (
          <NewResourceButton href="/tools/new" tooltip="Define and register a new computational tool" />
        )}
      </div>

      {/* Search + Category filter */}
      {total > 10 && (
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <input
            type="text"
            placeholder="Search tools..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="block w-full max-w-md rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <div className="flex gap-1 flex-wrap">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
                  category === cat
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : tools.length === 0 ? (
        <p className="mt-6 text-gray-500">No tools found.</p>
      ) : tools.length <= 10 ? (
        <div className="mt-6 grid gap-6 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {tools.map((t) => (
            <ResourceCard
              key={t.id}
              name={t.name}
              description={t.description}
              tags={t.tags}
              href={`/tools/${t.slug}`}
              isFollowed={isFollowed(t.id)}
              onToggleFollow={() => toggle(t.id)}
              metadata={[
                { label: "Creation", value: <>{t.creator_name || t.created_by} on {new Date(t.created_at).toLocaleDateString()}</> },
                ...(t.updated_by ? [{ label: "Update", value: <>{t.updated_by_name || t.updated_by} on {new Date(t.updated_at).toLocaleDateString()}</> }] : []),
              ]}
              badges={
                <>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">{t.org_name || t.org_id}</span>
                  {t.is_public && <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Public</span>}
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_COLORS[t.tool_type] || "bg-gray-100"}`}>
                    {t.tool_type}
                  </span>
                  {t.latest_version != null && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      t.latest_version_status === "active" ? "bg-green-100 text-green-700" :
                      t.latest_version_status === "deprecated" ? "bg-red-100 text-red-700" :
                      t.latest_version_status === "testing" ? "bg-yellow-100 text-yellow-700" :
                      "bg-gray-100 text-gray-600"
                    }`}>
                      v{t.latest_version} {t.latest_version_status}
                    </span>
                  )}
                </>
              }
            />
          ))}
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Version</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Category</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Public</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Organization</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Creator</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Updated By</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {tools.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <Link href={`/tools/${t.slug}`} className="font-medium text-blue-600 hover:underline">
                        {t.name}
                      </Link>
                      <FollowIconButton
                        followed={isFollowed(t.id)}
                        onClick={() => toggle(t.id)}
                      />
                    </div>
                    {t.description && <p className="text-xs text-gray-500 truncate max-w-xs">{t.description}</p>}
                    {t.tags.length > 0 && (
                      <div className="mt-1 flex gap-1 flex-wrap">
                        {t.tags.slice(0, 3).map((tag) => (
                          <span key={tag} className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-500">{tag}</span>
                        ))}
                        {t.tags.length > 3 && <span className="text-[10px] text-gray-400">+{t.tags.length - 3}</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {t.latest_version != null ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span className="font-medium">v{t.latest_version}</span>
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                          t.latest_version_status === "active" ? "bg-green-100 text-green-700" :
                          t.latest_version_status === "deprecated" ? "bg-red-100 text-red-700" :
                          t.latest_version_status === "testing" ? "bg-yellow-100 text-yellow-700" :
                          "bg-gray-100 text-gray-600"
                        }`}>{t.latest_version_status}</span>
                        {t.version_count > 1 && (
                          <span className="text-[10px] text-gray-400">({t.version_count} total)</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_COLORS[t.tool_type] || "bg-gray-100"}`}>
                      {t.tool_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    <span className="rounded-full bg-gray-100 px-2 py-1 text-xs">{t.category}</span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.is_public ? "Yes" : "No"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.org_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.creator_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.updated_by_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{new Date(t.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
