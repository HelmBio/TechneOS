"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, type Pipeline, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSubscriptions } from "@/lib/use-subscriptions";
import { hasPermission } from "@/lib/rbac";
import { FollowIconButton } from "@/components/follow-icon-button";
import { ResourceCard } from "@/components/resource-card";
import { NewResourceButton } from "@/components/new-resource-button";
import { useLabel } from "@/lib/labels";

export default function PipelinesPage() {
  const { user, loading: authLoading, permissions } = useAuth();
  const pipelinesLabel = useLabel("resource.pipeline.plural");
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const { isFollowed, toggle } = useSubscriptions("pipeline");

  useEffect(() => {
    if (authLoading || !user) return;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<Pipeline>>("/api/v1/pipelines", { skip: "0", limit: "50" });
        setPipelines(data.items);
        setTotal(data.total);
      } catch {
        setPipelines([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user) return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to view pipelines.</p>;

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{pipelinesLabel}</h1>
          {total > 0 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {total}
            </span>
          )}
        </div>
        {hasPermission(permissions, "pipeline", "create", "*") && <NewResourceButton href="/pipelines/new" tooltip="Create and register a new pipeline DAG" />}
      </div>

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : pipelines.length === 0 ? (
        <p className="mt-6 text-gray-500">No pipelines found.</p>
      ) : pipelines.length <= 10 ? (
        <div className="mt-6 grid gap-6 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {pipelines.map((p) => (
            <ResourceCard
              key={p.id}
              name={p.name}
              description={p.description}
              tags={p.tags}
              href={`/pipelines/${p.slug}`}
              isFollowed={isFollowed(p.id)}
              onToggleFollow={() => toggle(p.id)}
              metadata={[
                { label: "Creation", value: <>{p.creator_name || p.created_by_email || p.created_by} on {new Date(p.created_at).toLocaleDateString()}</> },
                ...(p.updated_by ? [{ label: "Update", value: <>{p.updated_by_name || p.updated_by} on {new Date(p.updated_at).toLocaleDateString()}</> }] : []),
              ]}
              badges={
                <>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">{p.org_name || p.org_id}</span>
                  {p.is_public && <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Public</span>}
                  <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-800">{p.pipeline_type}</span>
                  {/* <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">{p.category}</span> */}
                  {(p.latest_version ?? p.version) && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      p.latest_version_status === "active" ? "bg-green-100 text-green-700" :
                      p.latest_version_status === "deprecated" ? "bg-red-100 text-red-700" :
                      p.latest_version_status === "testing" ? "bg-yellow-100 text-yellow-700" :
                      "bg-gray-100 text-gray-600"
                    }`}>
                      v{p.latest_version ?? p.version} {p.latest_version_status}
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
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Public</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Organization</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Creator</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {pipelines.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <Link href={`/pipelines/${p.slug}`} className="font-medium text-blue-600 hover:underline">
                        {p.name}
                      </Link>
                      <FollowIconButton
                        followed={isFollowed(p.id)}
                        onClick={() => toggle(p.id)}
                      />
                    </div>
                    {p.description && <p className="text-xs text-gray-500 truncate max-w-xs">{p.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {p.latest_version != null ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span className="font-medium">v{p.latest_version}</span>
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                          p.latest_version_status === "active" ? "bg-green-100 text-green-700" :
                          p.latest_version_status === "deprecated" ? "bg-red-100 text-red-700" :
                          p.latest_version_status === "testing" ? "bg-yellow-100 text-yellow-700" :
                          "bg-gray-100 text-gray-600"
                        }`}>{p.latest_version_status}</span>
                        {p.version_count > 1 && (
                          <span className="text-[10px] text-gray-400">({p.version_count} total)</span>
                        )}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5">
                        <span className="font-medium">v{p.version}</span>
                        <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">unversioned</span>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{p.is_public ? "Yes" : "No"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{p.org_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{p.created_by_email ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{new Date(p.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
