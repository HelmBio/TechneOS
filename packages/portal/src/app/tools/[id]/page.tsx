"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  type PaginatedResponse,
  type ToolRun,
  type ToolWithVersions,
  type SubscriptionCheck,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/rbac";
import { INPUT_TYPE_COLORS, inputKindsFor } from "@/lib/input-kinds";
import ToolRunPanel from "@/components/tool/run-panel";
import { ToolMetadataModal } from "@/components/tool/metadata-modal";
import { ToolVersionEditorModal } from "@/components/tool/version-editor-modal";
import { DetailHeader } from "@/components/tool/detail-header";
import { DetailMetadata } from "@/components/tool/detail-metadata";
import { DetailReadme } from "@/components/tool/detail-readme";
import { DetailVersionsSection } from "@/components/tool/detail-versions-section";
import { DetailRunHistoryHeader } from "@/components/tool/detail-run-history-header";
import { StatusBadge } from "@/components/run/status-badge";
import { formatDuration } from "@/lib/run-utils";


export default function ToolDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading } = useAuth();
  const [tool, setTool] = useState<ToolWithVersions | null>(null);
  const [loading, setLoading] = useState(true);
  const [subCheck, setSubCheck] = useState<SubscriptionCheck | null>(null);
  const [subLoading, setSubLoading] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState<string | null>(null);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAddVersionModal, setShowAddVersionModal] = useState(false);
  const [updateVersionId, setUpdateVersionId] = useState<string | null>(null);
  const [selectedRunVersion, setSelectedRunVersion] = useState<ToolWithVersions["versions"][0] | null>(null);
  const [runs, setRuns] = useState<ToolRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsOpen, setRunsOpen] = useState(true);

  const fetchTool = useCallback(() => {
    if (!id) return;
    setLoading(true);
    apiGet<ToolWithVersions>(`/api/v1/tools/${id}`)
      .then(setTool)
      .catch(() => setTool(null))
      .finally(() => setLoading(false));
  }, [id]);

  const fetchSubscription = useCallback(() => {
    if (!id) return;
    apiGet<SubscriptionCheck>("/api/v1/subscriptions/check", {
      resource_type: "tool",
      resource_id: id,
    })
      .then(setSubCheck)
      .catch(() => setSubCheck(null));
  }, [id]);

  useEffect(() => {
    if (authLoading || !user) return;
    fetchTool();
    fetchSubscription();
  }, [user, authLoading, fetchTool, fetchSubscription]);

  useEffect(() => {
    if (!tool) return;
    let cancelled = false;
    const load = () =>
      apiGet<PaginatedResponse<ToolRun>>("/api/v1/tool-runs", {
        tool_id: tool.id,
        limit: "10",
      })
        .then((data) => {
          if (!cancelled) { setRuns(data.items); setRunsTotal(data.total); }
        })
        .catch(() => {
          if (!cancelled) setRuns([]);
        })
        .finally(() => {
          if (!cancelled) setRunsLoading(false);
        });
    load();
    const t = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, [tool]);

  const handleFollow = async () => {
    if (!id) return;
    setSubLoading(true);
    try {
      if (subCheck?.subscribed && subCheck.subscription_id) {
        await apiDelete(`/api/v1/subscriptions/${subCheck.subscription_id}`);
      } else {
        await apiPost("/api/v1/subscriptions", {
          resource_type: "tool",
          resource_id: id,
        });
      }
      fetchSubscription();
    } catch {
      // ignore
    } finally {
      setSubLoading(false);
    }
  };

  const handleVersionStatusChange = async (versionId: string, status: string) => {
    if (!tool) return;
    setStatusUpdating(versionId);
    try {
      await apiPatch(`/api/v1/tools/${tool.id}/versions/${versionId}`, { status });
      fetchTool();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to change version status");
    } finally {
      setStatusUpdating(null);
    }
  };

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please <a href="/login" className="text-blue-600 underline">log in</a> to view tools.
      </p>
    );
  if (loading) return <p className="p-8 text-gray-500">Loading tool...</p>;
  if (!tool) return <p className="p-8 text-red-500">Tool not found.</p>;

  const permissions = user?.permissions || [];
  const canCreateVersion = hasPermission(permissions, "tool", "create", "own");
  const canUpdate = (hasPermission(permissions, "tool", "update", "org") || (hasPermission(permissions, "tool", "update", "own") && tool.created_by === user.id)) && (tool.org_id === user.org_id || hasPermission(permissions, "tool", "update", "platform"));

  return (
    <div className="space-y-6">
      <DetailHeader
        name={tool.name}
        kind="tool"
        isFollowed={subCheck?.subscribed ?? false}
        subLoading={subLoading}
        onToggleFollow={handleFollow}
        breadcrumbLabel={tool.slug}
        onEdit={canUpdate ? () => setShowEditModal(true) : undefined}
        onExport={() => {
          const data = {
            name: tool.name,
            slug: tool.slug,
            description: tool.description,
            category: tool.category,
            tool_type: tool.tool_type,
            tags: tool.tags,
            is_public: tool.is_public,
            readme: tool.readme,
            versions: tool.versions.map((v) => ({
              version: v.version,
              status: v.status,
              docker_image: v.docker_image,
              docker_tag: v.docker_tag,
              package_name: v.package_name,
              package_version: v.package_version,
              entry_point: v.entry_point,
              assignment_type: v.assignment_type,
              default_assignee: v.default_assignee,
              due_in_hours: v.due_in_hours,
              require_attachments: v.require_attachments,
              input_schema: v.input_schema,
              output_schema: v.output_schema,
              parameters_schema: v.parameters_schema,
              resource_requirements: v.resource_requirements,
              changelog: v.changelog,
            })),
          };
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${tool.slug}.json`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        }}
      />

      <DetailMetadata
        description={tool.description}
        creatorName={tool.creator_name || tool.created_by}
        createdAt={tool.created_at}
        updatedByName={tool.updated_by ? (tool.updated_by_name || tool.updated_by) : null}
        updatedAt={tool.updated_by ? tool.updated_at : null}
        tags={tool.tags}
        isPublic={tool.is_public}
        orgName={tool.org_name}
        badges={
          <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-sm font-medium text-purple-800">{tool.tool_type}</span>
        }
      />

      <DetailReadme readme={tool.readme} name={tool.name} />

      {/* Version history */}
      <DetailVersionsSection
        versions={tool.versions}
        canCreateVersion={canCreateVersion}
        canUpdate={canUpdate}
        toolSlug={tool.slug}
        toolType={tool.tool_type}
        toolId={tool.id}
        statusUpdating={statusUpdating}
        onAddVersion={() => setShowAddVersionModal(true)}
        onUpdateVersion={(vid) => setUpdateVersionId(vid)}
        onStatusChange={handleVersionStatusChange}
        onStartRunVersion={(vid) => {
          const v = tool.versions.find((x) => x.id === vid);
          if (v) setSelectedRunVersion(v);
        }}
      />

      {/* Recent runs */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <DetailRunHistoryHeader
          count={runsTotal}
          open={runsOpen}
          onToggle={() => setRunsOpen(!runsOpen)}
        />
        {runsOpen && (
          <div className="px-4 pb-4">
            {(() => {
              if (runsLoading) return <p className="text-sm text-gray-500">Loading runs...</p>;
              if (runs.length === 0) return <p className="text-sm text-gray-500">No runs yet.</p>;
              return (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Run</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Version</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Input Type</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Submitted By</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Submitted On</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Duration</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                      {runs.map((r) => (
                        <tr key={r.id} className="hover:bg-gray-50">
                          <td className="px-4 py-2">
                            <Link
                              href={`/tool-runs/${r.id}`}
                              className="font-mono text-sm text-blue-600 hover:underline"
                            >
                              {`${r.id.slice(0, 12)}...`}
                            </Link>
                          </td>
                          <td className="px-4 py-2 text-sm text-gray-600">
                            {r.tool_version_num != null ? `v${r.tool_version_num}` : "\u2014"}
                          </td>
                          <td className="px-4 py-2">
                            {(() => {
                              const kinds = inputKindsFor(r);
                              if (kinds.length === 0) {
                                return <span className="text-sm text-gray-400">\u2014</span>;
                              }
                              return (
                                <div className="flex flex-wrap gap-1">
                                  {kinds.map((k) => (
                                    <span
                                      key={k}
                                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${INPUT_TYPE_COLORS[k]}`}
                                    >
                                      {k}
                                    </span>
                                  ))}
                                </div>
                              );
                            })()}
                          </td>
                          <td className="px-4 py-2">
                            <StatusBadge status={r.status} />
                          </td>
                          <td className="px-4 py-2 text-sm text-gray-600">
                            {r.submitted_by_email || r.submitted_by.slice(0, 12) + "..."}
                          </td>
                          <td className="px-4 py-2 text-sm text-gray-500">
                            {new Date(r.created_at).toLocaleString()}
                          </td>
                          <td className="px-4 py-2 text-sm text-gray-500">
                            {formatDuration(r.started_at, r.finished_at, r.status)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })()}
          </div>
        )}
      </div>

      {/* Run modal */}
      {selectedRunVersion && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="flex max-h-[90vh] w-full max-w-xl flex-col rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">
                Run {tool.name} · v{selectedRunVersion.version}
              </h2>
              <button
                onClick={() => setSelectedRunVersion(null)}
                className="rounded p-1 text-gray-400 hover:text-gray-600"
              >
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="overflow-y-auto p-6">
              <ToolRunPanel
                toolId={tool.id}
                toolSlug={tool.slug}
                version={selectedRunVersion}
                onCancel={() => setSelectedRunVersion(null)}
              />
            </div>
          </div>
        </div>
      )}

      {showEditModal && (
        <ToolMetadataModal
          tool={tool}
          onClose={() => setShowEditModal(false)}
          onUpdate={fetchTool}
        />
      )}
      {showAddVersionModal && (
        <ToolVersionEditorModal
          toolId={tool.id}
          toolName={tool.name}
          toolType={tool.tool_type}
          versionId={null}
          versionNumber={null}
          version={null}
          previousVersion={tool.versions.length > 0 ? tool.versions.reduce((prev, curr) => prev.version > curr.version ? prev : curr) : null}
          onClose={() => { setShowAddVersionModal(false); setUpdateVersionId(null); }}
          onComplete={() => { fetchTool(); setShowAddVersionModal(false); setUpdateVersionId(null); }}
        />
      )}
      {updateVersionId && (
        <ToolVersionEditorModal
          toolId={tool.id}
          toolName={tool.name}
          toolType={tool.tool_type}
          versionId={updateVersionId}
          versionNumber={tool.versions.find(v => v.id === updateVersionId)?.version || null}
          version={tool.versions.find(v => v.id === updateVersionId) || null}
          onClose={() => { setUpdateVersionId(null); setShowAddVersionModal(false); }}
          onComplete={() => { fetchTool(); setUpdateVersionId(null); }}
        />
      )}
    </div>
  );
}
