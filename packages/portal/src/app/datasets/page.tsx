"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, type Dataset, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLabel } from "@/lib/labels";
import { useSubscriptions } from "@/lib/use-subscriptions";
import { hasPermission } from "@/lib/rbac";
import { ResourceCard } from "@/components/resource-card";
import { FollowIconButton } from "@/components/follow-icon-button";
import { NewResourceButton } from "@/components/new-resource-button";

function formatSize(bytes: number): string {
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (bytes < 1024) return `${bytes.toFixed(bytes < 10 && unit !== "B" ? 1 : 0)} ${unit}`;
    bytes /= 1024;
  }
  return `${bytes.toFixed(1)} TB`;
}

export default function DatasetsPage() {
  const datasetsLabel = useLabel("resource.dataset.plural");
  const { user, loading: authLoading, permissions } = useAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const { isFollowed, toggle } = useSubscriptions("dataset");

  useEffect(() => {
    if (authLoading || !user) return;
    const params: Record<string, string> = { skip: "0", limit: "50" };
    if (search) params.q = search;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<Dataset>>("/api/v1/datasets", params);
        setDatasets(data.items);
        setTotal(data.total);
      } catch {
        setDatasets([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, search]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user) return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to view datasets.</p>;

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{datasetsLabel}</h1>
          {total > 0 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {total}
            </span>
          )}
        </div>
        {hasPermission(permissions, "dataset", "create", "*") && <NewResourceButton href="/datasets/new" tooltip="Register new dataset definition" />}
      </div>

      {total > 10 && (
        <input
          type="text"
          placeholder="Search datasets..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mt-4 block w-full max-w-md rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      )}

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : datasets.length === 0 ? (
        <p className="mt-6 text-gray-500">No datasets found.</p>
      ) : datasets.length <= 10 ? (
        <div className="mt-6 grid gap-6 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {datasets.map((ds) => (
            <ResourceCard
              key={ds.id}
              name={ds.name}
              description={ds.description}
              tags={ds.tags}
              href={`/datasets/${ds.slug}`}
              isFollowed={isFollowed(ds.id)}
              onToggleFollow={() => toggle(ds.id)}
              metadata={[
                { label: "Created", value: <>{ds.creator_name || ds.created_by} on {new Date(ds.created_at).toLocaleDateString()}</> },
                ...(ds.updated_by ? [{ label: "Updated", value: <>{ds.updated_by_name || ds.updated_by} on {new Date(ds.updated_at).toLocaleDateString()}</> }] : []),
                { label: "Files", value: <>{ds.total_file_count} file{ds.total_file_count !== 1 ? "s" : ""} ({formatSize(ds.total_size)})</> },
              ]}
              badges={
                <>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">{ds.org_name || ds.org_id}</span>
                  {ds.is_public && <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Public</span>}
                  <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">{ds.data_type}</span>
                  {ds.version_count > 0 && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      ds.latest_version_status === "active" ? "bg-green-100 text-green-700" :
                      ds.latest_version_status === "deprecated" ? "bg-red-100 text-red-700" :
                      ds.latest_version_status === "testing" ? "bg-yellow-100 text-yellow-700" :
                      "bg-blue-100 text-blue-800"
                    }`}>
                      v{ds.latest_version} {ds.latest_version_status}
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
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Format</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Versions</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Creator</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Updated By</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Organization</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Public</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {datasets.map((ds) => (
                <tr key={ds.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <Link href={`/datasets/${ds.slug}`} className="font-medium text-blue-600 hover:underline">
                        {ds.name}
                      </Link>
                      <FollowIconButton
                        followed={isFollowed(ds.id)}
                        onClick={() => toggle(ds.id)}
                      />
                    </div>
                    {ds.description && <p className="text-xs text-gray-500 truncate max-w-xs">{ds.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{ds.data_type}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{ds.file_format ? ds.file_format.toUpperCase() : "\u2014"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {ds.version_count > 0 ? (
                      <div className="flex items-center gap-1.5">
                        <span>{ds.version_count} version{ds.version_count > 1 ? "s" : ""}{ds.total_size > 0 ? `, ${formatSize(ds.total_size)}` : ""}</span>
                        {ds.latest_version != null && (
                          <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800">
                            v{ds.latest_version} latest
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-400">None</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{ds.creator_name ?? "\u2014"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{ds.updated_by_name ?? "\u2014"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{ds.org_name ?? "\u2014"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{ds.is_public ? "Yes" : "No"}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{new Date(ds.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
