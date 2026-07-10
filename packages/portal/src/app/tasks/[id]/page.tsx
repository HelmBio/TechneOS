"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  apiGet,
  apiPatch,
  apiPost,
  apiUploadTaskInput,
  type ToolWithVersions,
  type ToolVersion,
  type HumanTaskRun,
  type PaginatedResponse,
  type TaskInputUploadResponse,
} from "@/lib/api";
import {
  DataPanel,
  type DataPanelState,
} from "@/components/task-run/data-panel";
import { SchemaForm, collectDefaults } from "@/components/schema-form";
import { useAuth } from "@/lib/auth";
import { DetailRunHistoryHeader } from "@/components/tool/detail-run-history-header";
import TaskRunTable from "@/components/tool/task-run-table";
import { useSubscriptions } from "@/lib/use-subscriptions";
import { hasPermission } from "@/lib/rbac";
import { ToolMetadataModal } from "@/components/tool/metadata-modal";
import { ToolVersionEditorModal } from "@/components/tool/version-editor-modal";
import { DetailHeader } from "@/components/tool/detail-header";
import { DetailMetadata } from "@/components/tool/detail-metadata";
import { DetailReadme } from "@/components/tool/detail-readme";
import { DetailVersionsSection } from "@/components/tool/detail-versions-section";
function isEmpty(obj: unknown): boolean {
  return !obj || (typeof obj === "object" && Object.keys(obj).length === 0);
}

function validateInputSchema(
  inputSchema: Record<string, unknown>,
  data: Record<string, unknown>,
): string[] {
  const errors: string[] = [];

  if (!inputSchema || typeof inputSchema !== "object") {
    return errors;
  }

  const schema = inputSchema as {
    type?: string;
    properties?: Record<string, unknown>;
    required?: string[];
  };
  const required = schema.required || [];

  for (const field of required) {
    if (
      !(field in data) ||
      data[field] === undefined ||
      data[field] === null ||
      data[field] === ""
    ) {
      errors.push(`Missing required field: ${field}`);
    }
  }

  if (data.compounds !== undefined && data.compounds !== null) {
    if (!Array.isArray(data.compounds)) {
      errors.push("compounds must be an array");
    } else {
      for (let i = 0; i < data.compounds.length; i++) {
        const compound = data.compounds[i] as Record<string, unknown>;
        if (!compound.id) {
          errors.push(`Compound at index ${i} is missing required field: id`);
        }
      }
    }
  }

  if (data.file_format && schema.properties?.file_format) {
    const fileFormatSchema = schema.properties.file_format as {
      enum?: string[];
      default?: string;
    };
    if (
      fileFormatSchema.enum &&
      !fileFormatSchema.enum.includes(data.file_format as string)
    ) {
      errors.push(
        `file_format must be one of: ${fileFormatSchema.enum.join(", ")}`,
      );
    }
  }

  return errors;
}

function pickRunnableVersion(
  versions: ToolVersion[] | undefined,
): ToolVersion | null {
  if (!versions || versions.length === 0) return null;
  const active = versions.find((v) => v.status === "active");
  if (active) return active;
  const testing = versions.find((v) => v.status === "testing");
  if (testing) return testing;
  return null;
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [tool, setTool] = useState<ToolWithVersions | null>(null);
  const [assignments, setAssignments] = useState<HumanTaskRun[]>([]);
  const [assignmentsTotal, setAssignmentsTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // Create Task Run modal
  const [showModal, setShowModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [paramValues, setParamValues] = useState<Record<string, unknown>>({});
  const [inputDataState, setInputDataState] = useState<DataPanelState>({
    method: "paste",
    pasteContent: "",
    uploadResult: null,
    uploadedFile: null,
  });
  const [validationError, setValidationError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const [users, setUsers] = useState<
    { id: string; email: string; full_name: string | null }[]
  >([]);
  const [teams, setTeams] = useState<{ slug: string; name: string }[]>([]);

  // Dedicated Assignment section state (no longer embedded in parameters_schema)
  const [assignedUserId, setAssignedUserId] = useState<string>("");
  const [assignedTeamSlug, setAssignedTeamSlug] = useState<string>("");
  const [assignmentType, setAssignmentType] = useState<string>("team");
  const [dueInHours, setDueInHours] = useState<number | null>(null);
  const [priority, setPriority] = useState<string>("medium");
  const [projectLeadId, setProjectLeadId] = useState<string>("");

  // Edit / version modals
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAddVersionModal, setShowAddVersionModal] = useState(false);
  const [updateVersionId, setUpdateVersionId] = useState<string | null>(null);
  const [statusUpdating, setStatusUpdating] = useState<string | null>(null);
  const [runsOpen, setRunsOpen] = useState(true);

  const { isFollowed, toggle } = useSubscriptions("tool");

  const fetchTool = useCallback(() => {
    if (!id) return;
    apiGet<ToolWithVersions>(`/api/v1/tools/${id}`)
      .then(setTool)
      .catch(() => setTool(null));
  }, [id]);

  useEffect(() => {
    if (authLoading || !user || !id) return;
    setLoading(true);
    apiGet<ToolWithVersions>(`/api/v1/tools/${id}`)
      .then((toolData) => {
        setTool(toolData);
        return apiGet<PaginatedResponse<HumanTaskRun>>(
          `/api/v1/task-runs?tool_slug=${toolData.slug}&limit=20`,
        ).catch(() => null);
      })
      .then((assignmentsData) => {
        if (assignmentsData) {
          setAssignments(assignmentsData.items);
          setAssignmentsTotal(assignmentsData.total);
        }
      })
      .catch(() => setTool(null))
      .finally(() => setLoading(false));
  }, [id, user, authLoading]);

  // Scroll to error box when it appears.
  useEffect(() => {
    if (formError || validationError) {
      errorRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [formError, validationError]);

  const closeModal = useCallback(() => {
    setShowModal(false);
    setSubmitting(false);
    setValidationError(null);
    setFormError(null);
    setInputDataState({
      method: "paste",
      pasteContent: "",
      uploadResult: null,
      uploadedFile: null,
    });
    setParamValues({});
    setUsers([]);
    setTeams([]);
    setAssignedUserId("");
    setAssignedTeamSlug("");
    setAssignmentType("team");
    setDueInHours(null);
    setPriority("medium");
  }, []);

  // Versions runnable from the Create Task Run modal — active first, then testing.
  // Draft / deprecated versions are intentionally hidden from the picker.
  const runnableVersions = (tool?.versions ?? []).filter(
    (v) => v.status === "active" || v.status === "testing",
  );
  const selectedVersion =
    runnableVersions.find((v) => v.id === selectedVersionId) ?? null;

  useEffect(() => {
    if (!selectedVersion) return;
    const paramsSchema = selectedVersion.parameters_schema as
      | Record<string, unknown>
      | undefined;
    const props =
      (paramsSchema?.properties as
        | Record<string, Record<string, unknown>>
        | undefined) ?? {};
    setParamValues(collectDefaults(props));
    setAssignmentType(selectedVersion.assignment_type || "team");
    setAssignedUserId("");
    setAssignedTeamSlug(selectedVersion.default_assignee ?? "");
    setDueInHours(selectedVersion.due_in_hours ?? null);
    setPriority(selectedVersion.priority || "medium");
  }, [selectedVersion]);

  useEffect(() => {
    if (!showModal || !tool) return;

    // Version is preselected via onStartRunVersion from VersionCard play button.
    // If somehow not set, fall back to the first runnable version.
    const initial = selectedVersionId
      ? (runnableVersions.find((v) => v.id === selectedVersionId) ??
          pickRunnableVersion(tool.versions))
      : pickRunnableVersion(tool.versions);

    if (initial) {
      const paramsSchema = initial.parameters_schema as
        | Record<string, unknown>
        | undefined;
      const props =
        (paramsSchema?.properties as
          | Record<string, Record<string, unknown>>
          | undefined) ?? {};
      setParamValues(collectDefaults(props));
      setAssignmentType(initial.assignment_type || "team");
      setAssignedUserId("");
      setAssignedTeamSlug(initial.default_assignee ?? "");
      setDueInHours(initial.due_in_hours ?? null);
      setPriority(initial.priority || "medium");
    } else {
      setParamValues({});
      setAssignmentType("team");
      setAssignedUserId("");
      setAssignedTeamSlug("");
      setDueInHours(null);
      setPriority("medium");
    }
    setInputDataState({
      method: "paste",
      pasteContent: "",
      uploadResult: null,
      uploadedFile: null,
    });
    setValidationError(null);
    setFormError(null);

    setLoadingUsers(true);
    Promise.all([
      apiGet<{
        items: { id: string; email: string; full_name: string | null }[];
      }>("/api/v1/users?limit=200").catch(() => ({ items: [] })),
      apiGet<{ items: { slug: string; name: string }[] }>(
        "/api/v1/teams?limit=200",
      ).catch(() => ({ items: [] })),
    ])
      .then(([usersData, teamsData]) => {
        setUsers(usersData.items ?? []);
        setTeams(teamsData.items ?? []);
      })
      .finally(() => setLoadingUsers(false));
  }, [showModal, tool]);

  const handleAssign = async () => {
    if (!tool) return;
    if (!selectedVersion) {
      setValidationError("The selected version is not runnable.");
      return;
    }
    const inputSchema = selectedVersion.input_schema as
      | Record<string, unknown>
      | undefined;
    const needsInput = inputSchema && !isEmpty(inputSchema);

    setValidationError(null);

    // Build input_snapshot from task parameters only — no assignment fields
    // or input data (those go via /from-tool/upload and top-level body fields).
    const inputSnapshot: Record<string, unknown> = { ...paramValues };
    delete inputSnapshot.assignment_details;

    const ids: string[] = [];
    if (needsInput) {
      if (inputDataState.method === "file") {
        if (!inputDataState.uploadedFile) {
          setValidationError("Please select an input file.");
          return;
        }
        if (!inputDataState.uploadResult) {
          setValidationError("Input file must be uploaded first.");
          return;
        }
        ids.push(
          (inputDataState.uploadResult as TaskInputUploadResponse).input_id,
        );
      } else {
        if (!inputDataState.pasteContent.trim()) {
          setValidationError("Please paste input data.");
          return;
        }
        // Upload pasted content as a file before creating the task run.
        setSubmitting(true);
        try {
          const blob = new Blob([inputDataState.pasteContent], {
            type: "text/plain",
          });
          const file = new File(
            [blob],
            `input.${(paramValues.input_file_format as string) || "txt"}`,
            { type: "text/plain" },
          );
          const uploadResult = await apiUploadTaskInput(tool.slug, selectedVersion.id, file);
          ids.push(uploadResult.input_id);
        } catch (err: unknown) {
          let msg = "Failed to upload pasted input";
          if (err && typeof err === "object" && "detail" in err) {
            msg = (err as { detail: string }).detail;
          } else if (err instanceof Error) {
            msg = err.message;
          }
          setValidationError(msg);
          setSubmitting(false);
          return;
        }
      }
    }

    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        tool_slug: tool.slug,
        tool_version_id: selectedVersion.id,
        input_snapshot: inputSnapshot,
        input_ids: ids,
      };
      if (assignedUserId) {
        body.assigned_user_id = assignedUserId;
      } else if (assignedTeamSlug) {
        body.assigned_team_slug = assignedTeamSlug;
      }
      if (dueInHours != null) body.due_in_hours = dueInHours;
      if (priority) body.priority = priority;
      if (projectLeadId) {
        const lead = users.find((u) => u.id === projectLeadId);
        if (lead) body.project_lead_email = lead.email;
      }
      const a = await apiPost<HumanTaskRun>(
        "/api/v1/task-runs/from-tool",
        body,
      );
      closeModal();
      router.push(`/task-runs/${a.id}`);
    } catch (err: unknown) {
      setSubmitting(false);
      let errorMsg = "Failed to create assignment";
      if (err && typeof err === "object" && "response" in err) {
        const response = (err as { response?: { data?: { detail?: string } } })
          .response;
        if (response?.data?.detail) {
          errorMsg = response.data.detail;
        }
      } else if (err instanceof Error) {
        errorMsg = err.message;
      }
      setFormError(errorMsg);
    }
  };

  const handleVersionStatusChange = async (
    versionId: string,
    status: string,
  ) => {
    if (!tool) return;
    setStatusUpdating(versionId);
    try {
      await apiPatch(`/api/v1/tools/${tool.id}/versions/${versionId}`, {
        status,
      });
      fetchTool();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to change version status");
    } finally {
      setStatusUpdating(null);
    }
  };

  if (authLoading || loading)
    return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>{" "}
        to view this task.
      </p>
    );
  if (!tool || tool.tool_type !== "human")
    return <p className="p-8 text-gray-500">Task not found.</p>;

  const permissions = user?.permissions || [];
  const canUpdate =
    (hasPermission(permissions, "tool", "update", "org") ||
      (hasPermission(permissions, "tool", "update", "own") &&
        tool.created_by === user.id)) &&
    (tool.org_id === user.org_id ||
      hasPermission(permissions, "tool", "update", "platform"));
  const canCreateVersion = hasPermission(permissions, "tool", "create", "own");
  const latestVersion =
    tool.versions.length > 0
      ? tool.versions.reduce((prev, curr) =>
          prev.version > curr.version ? prev : curr,
        )
      : null;

  return (
    <div className="space-y-6">
      <DetailHeader
        name={tool.name}
        kind="task"
        isFollowed={isFollowed(tool.id)}
        onToggleFollow={() => toggle(tool.id)}
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
          const blob = new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json",
          });
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
          if (v) {
            setSelectedVersionId(v.id);
            setShowModal(true);
          }
        }}
      />

      {/* Recent Task Runs */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <DetailRunHistoryHeader
          count={assignmentsTotal}
          open={runsOpen}
          onToggle={() => setRunsOpen(!runsOpen)}
        />
        {runsOpen && (
          <div className="px-4 pb-4">
            <TaskRunTable taskRuns={assignments.slice(0, 10)} />
          </div>
        )}
      </div>

      {/* Create Task Run Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="flex max-h-[90vh] w-full max-w-xl flex-col rounded-lg bg-white shadow-xl">
            <div className="border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-1.5 flex-wrap">
                Start a task run for
                <span className="font-bold text-indigo-600">{tool.slug}</span>
                <span className="text-xs font-medium text-gray-500 bg-gray-100 rounded-full px-2.5 py-0.5">
                  v{selectedVersion?.version} ({selectedVersion?.status})
                </span>
              </h2>
            </div>

            <div className="overflow-y-auto px-6 py-4 space-y-4">
              {/* Parameters + Assignment */}
              {(() => {
                const paramsSchema = selectedVersion?.parameters_schema as
                  | Record<string, unknown>
                  | undefined;

                return (
                  <>
                    {/* Assignment section — dedicated fields from tool_human_configs */}
                    <h3 className="text-sm font-semibold text-gray-800 mb-2">
                      Assignment
                    </h3>
                    <div className="rounded-lg border border-gray-200 p-4 space-y-3">

                      <label className="block">
                        <span className="block text-sm font-medium text-gray-700 mb-1">
                          Assignment Type <span className="text-red-500">*</span>
                        </span>
                        <select
                          value={assignmentType}
                          onChange={(e) => {
                            setAssignmentType(e.target.value);
                            setAssignedUserId("");
                            setAssignedTeamSlug("");
                          }}
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                        >
                          <option value="user">User</option>
                          <option value="team">Team</option>
                        </select>
                      </label>

                      {assignmentType === "user" ? (
                        <label className="block">
                          <span className="block text-sm font-medium text-gray-700 mb-1">
                            Assigned User <span className="text-red-500">*</span>
                          </span>
                          <select
                            value={assignedUserId}
                            onChange={(e) => setAssignedUserId(e.target.value)}
                            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                          >
                            <option value="">Select user...</option>
                            {users.map((u) => (
                              <option key={u.id} value={u.id}>
                                {u.full_name || u.email}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : (
                        <label className="block">
                          <span className="block text-sm font-medium text-gray-700 mb-1">
                            Assigned Team <span className="text-red-500">*</span>
                          </span>
                          <select
                            value={assignedTeamSlug}
                            onChange={(e) => setAssignedTeamSlug(e.target.value)}
                            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                          >
                            <option value="">Select team...</option>
                            {teams.map((t) => (
                              <option key={t.slug} value={t.slug}>
                                {t.name}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}

                      <label className="block">
                        <span className="block text-sm font-medium text-gray-700 mb-1">
                          Priority <span className="text-red-500">*</span>
                        </span>
                        <select
                          value={priority}
                          onChange={(e) => setPriority(e.target.value)}
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                          <option value="urgent">Urgent</option>
                        </select>
                      </label>

                      <label className="block">
                        <span className="block text-sm font-medium text-gray-700 mb-1">
                          Due in (hours) <span className="text-red-500">*</span>
                        </span>
                        <input
                          type="number"
                          value={dueInHours ?? ""}
                          onChange={(e) =>
                            setDueInHours(
                              e.target.value ? Number(e.target.value) : null,
                            )
                          }
                          placeholder={
                            selectedVersion?.due_in_hours
                              ? `Default: ${selectedVersion.due_in_hours}`
                              : "72"
                          }
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                        />
                      </label>

                      <label className="block">
                        <span className="block text-sm font-medium text-gray-700 mb-1">
                          Project Lead
                        </span>
                        <select
                          value={projectLeadId}
                          onChange={(e) => setProjectLeadId(e.target.value)}
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                        >
                          <option value="">None</option>
                          {users.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.full_name || u.email}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    {paramsSchema && !isEmpty((paramsSchema.properties as Record<string, unknown> | undefined)) && (
                      <>
                        <h3 className="text-sm font-semibold text-gray-800 mb-2">
                          Task Parameters
                        </h3>
                        <div className="rounded-lg border border-gray-200 p-4 space-y-4">
                          <SchemaForm
                            schema={paramsSchema}
                            values={paramValues}
                            onChange={(v) => {
                              setParamValues(v);
                              setFormError(null);
                              setValidationError(null);
                            }}
                          />
                        </div>
                      </>
                    )}
                  </>
                );
              })()}

              {/* Input Data section */}
              {selectedVersion && !isEmpty(selectedVersion.input_schema) && (
                <>
                  <h3 className="text-sm font-semibold text-gray-800 mb-2">
                    Input Data <span className="text-red-500">*</span>
                  </h3>
                  <DataPanel
                    format={paramValues.input_file_format as string | undefined}
                    uploadFn={(file) => apiUploadTaskInput(tool.slug, selectedVersion!.id, file)}
                    onChange={(state) => {
                      setInputDataState(state);
                      setFormError(null);
                      setValidationError(null);
                    }}
                  />
                </>
              )}

              {(formError || validationError) && (
                <div
                  ref={errorRef}
                  className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 whitespace-pre-wrap"
                >
                  {formError || validationError}
                </div>
              )}
            </div>

            <div className="border-t border-gray-200 px-6 py-4 flex justify-end gap-2">
              <button
                onClick={closeModal}
                disabled={submitting}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAssign}
                disabled={submitting}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? "Submitting..." : "Submit"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Task Definition (tool-level fields only) */}
      {showEditModal && (
        <ToolMetadataModal
          tool={tool}
          kind="task"
          onClose={() => setShowEditModal(false)}
          onUpdate={fetchTool}
        />
      )}

      {/* New Version */}
      {showAddVersionModal && (
        <ToolVersionEditorModal
          toolId={tool.id}
          toolName={tool.name}
          toolType={tool.tool_type}
          versionId={null}
          versionNumber={null}
          version={null}
          previousVersion={latestVersion}
          onClose={() => setShowAddVersionModal(false)}
          onComplete={() => {
            fetchTool();
            setShowAddVersionModal(false);
          }}
          kind="task"
        />
      )}

      {/* Edit existing version */}
      {updateVersionId && (
        <ToolVersionEditorModal
          toolId={tool.id}
          toolName={tool.name}
          toolType={tool.tool_type}
          versionId={updateVersionId}
          versionNumber={
            tool.versions.find((v) => v.id === updateVersionId)?.version || null
          }
          version={tool.versions.find((v) => v.id === updateVersionId) || null}
          onClose={() => setUpdateVersionId(null)}
          onComplete={() => {
            fetchTool();
            setUpdateVersionId(null);
          }}
          kind="task"
        />
      )}
    </div>
  );
}
