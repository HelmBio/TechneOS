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

export default function TasksPage() {
  const tasksLabel = useLabel("resource.task.plural");
  const { user, loading: authLoading } = useAuth();
  const [tasks, setTasks] = useState<Tool[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const { isFollowed, toggle } = useSubscriptions("tool");

  useEffect(() => {
    if (authLoading || !user) return;
    const params: Record<string, string> = { skip: "0", limit: "50", tool_type: "human" };
    if (search) params.q = search;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<Tool>>("/api/v1/tools", params);
        setTasks(data.items);
        setTotal(data.total);
      } catch {
        setTasks([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, search]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user) return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to view tasks.</p>;

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{tasksLabel}</h1>
          {total > 0 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {total}
            </span>
          )}
        </div>
        {hasPermission(user.permissions || [], "tool", "create", "*") && (
          <NewResourceButton href="/tasks/new" tooltip="Define and register a new human task" />
        )}
      </div>

      {total > 10 && (
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <input
            type="text"
            placeholder="Search tasks..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="block w-full max-w-md rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      )}

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : tasks.length === 0 ? (
        <p className="mt-6 text-gray-500">No tasks found.</p>
      ) : tasks.length <= 10 ? (
        <div className="mt-6 grid gap-6 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {tasks.map((t) => (
            <ResourceCard
              key={t.id}
              name={t.name}
              description={t.description}
              tags={t.tags}
              href={`/tasks/${t.slug}`}
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
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">{t.tool_type}</span>
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
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Category</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Public</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Organization</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Creator</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {tasks.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <Link href={`/tasks/${t.slug}`} className="font-medium text-blue-600 hover:underline">
                        {t.name}
                      </Link>
                      <FollowIconButton followed={isFollowed(t.id)} onClick={() => toggle(t.id)} />
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
                    <span className="rounded-full bg-gray-100 px-2 py-1 text-xs">{t.category}</span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.is_public ? "Yes" : "No"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.org_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{t.creator_name ?? "—"}</td>
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
