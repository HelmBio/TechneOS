"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPut, type ToolVersion, type ComputeBackend, type ComputeArtifact } from "@/lib/api";

function Tooltip({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="group relative inline-flex">
      {children}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-xs text-white bg-gray-800 rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-10">
        {title}
      </span>
    </div>
  );
}

function AccordionItem({
  title,
  isOpen,
  onToggle,
  action,
  children,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-gray-200 rounded-lg mb-3">
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => e.key === "Enter" && onToggle()}
        className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-gray-50 cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-700">{title}</span>
          {action}
        </div>
        <svg
          className={`h-4 w-4 text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      {isOpen && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

export function ToolVersionEditorModal({
  toolId,
  toolName,
  toolType,
  versionId,
  versionNumber,
  version,
  previousVersion,
  onClose,
  onComplete,
  kind = "tool",
}: {
  toolId: string;
  toolName: string;
  toolType: string;
  versionId?: string | null;
  versionNumber?: number | null;
  version?: ToolVersion | null;
  previousVersion?: ToolVersion | null;
  onClose: () => void;
  onComplete: () => void;
  kind?: "tool" | "task";
}) {
  const isEditMode = !!versionId;

  const [dockerImage, setDockerImage] = useState("");
  const [dockerTag, setDockerTag] = useState("");
  const [packageName, setPackageName] = useState("");
  const [packageVersion, setPackageVersion] = useState("");
  const [entryPoint, setEntryPoint] = useState("");
  const [packageIndexUrl, setPackageIndexUrl] = useState("");
  const [assignmentType, setAssignmentType] = useState("user");
  const [defaultAssignee, setDefaultAssignee] = useState("");
  const [dueInHours, setDueInHours] = useState("72");
  const [requireAttachments, setRequireAttachments] = useState(false);
  const [priority, setPriority] = useState("medium");
  const [defaultProjectLeadEmail, setDefaultProjectLeadEmail] = useState("");
  const [inputSchemaJson, setInputSchemaJson] = useState("{}");
  const [outputSchemaJson, setOutputSchemaJson] = useState("{}");
  const [parametersSchemaJson, setParametersSchemaJson] = useState("{}");
  const [resourceRequirementsJson, setResourceRequirementsJson] = useState("{}");
  const [selectedBackend, setSelectedBackend] = useState("");
  const [computeBackends, setComputeBackends] = useState<ComputeBackend[]>([]);
  const [artifacts, setArtifacts] = useState<ComputeArtifact[]>([]);
  const [changelog, setChangelog] = useState("");

  useEffect(() => {
    if (isEditMode && version) {
      setDockerImage(version.docker_image || "");
      setDockerTag(version.docker_tag || "");
      setInputSchemaJson(version.input_schema ? JSON.stringify(version.input_schema, null, 2) : "{}");
      setOutputSchemaJson(version.output_schema ? JSON.stringify(version.output_schema, null, 2) : "{}");
      setParametersSchemaJson(version.parameters_schema ? JSON.stringify(version.parameters_schema, null, 2) : "{}");
      setResourceRequirementsJson(version.resource_requirements ? JSON.stringify(version.resource_requirements, null, 2) : "{}");
      setSelectedBackend((version.resource_requirements as Record<string, unknown>)?.backend as string || "");
      setChangelog(version.changelog || "");
      setPackageName(version.package_name || "");
      setPackageVersion(version.package_version || "");
      setEntryPoint(version.entry_point || "");
      setPackageIndexUrl(version.package_index_url || "");
      setAssignmentType(version.assignment_type || "user");
      setDefaultAssignee(version.default_assignee || "");
      setDueInHours(version.due_in_hours != null ? String(version.due_in_hours) : "72");
      setRequireAttachments(version.require_attachments || false);
      setPriority(version.priority || "medium");
      setDefaultProjectLeadEmail(version.default_project_lead_email || "");
    }
  }, [isEditMode, version]);

  useEffect(() => {
    if (isEditMode || !previousVersion) return;
    setDockerImage(previousVersion.docker_image || "");
    setDockerTag(previousVersion.docker_tag || "");
    setInputSchemaJson(previousVersion.input_schema ? JSON.stringify(previousVersion.input_schema, null, 2) : "{}");
    setOutputSchemaJson(previousVersion.output_schema ? JSON.stringify(previousVersion.output_schema, null, 2) : "{}");
    setParametersSchemaJson(previousVersion.parameters_schema ? JSON.stringify(previousVersion.parameters_schema, null, 2) : "{}");
    setResourceRequirementsJson(previousVersion.resource_requirements ? JSON.stringify(previousVersion.resource_requirements, null, 2) : "{}");
    setSelectedBackend((previousVersion.resource_requirements as Record<string, unknown>)?.backend as string || "");
    setChangelog("");
    setPackageName(previousVersion.package_name || "");
    setPackageVersion(previousVersion.package_version || "");
    setEntryPoint(previousVersion.entry_point || "");
    setPackageIndexUrl(previousVersion.package_index_url || "");
    setAssignmentType(previousVersion.assignment_type || "user");
    setDefaultAssignee(previousVersion.default_assignee || "");
    setDueInHours(previousVersion.due_in_hours != null ? String(previousVersion.due_in_hours) : "72");
    setRequireAttachments(previousVersion.require_attachments || false);
    setPriority(previousVersion.priority || "medium");
    setDefaultProjectLeadEmail(previousVersion.default_project_lead_email || "");
  }, [isEditMode, previousVersion]);

  useEffect(() => {
    setLoadingAssignees(true);
    Promise.all([
      apiGet<{ items: { id: string; email: string; full_name: string | null }[] }>("/api/v1/users?limit=200").catch(() => ({ items: [] })),
      apiGet<{ items: { slug: string; name: string }[] }>("/api/v1/teams?limit=200").catch(() => ({ items: [] })),
      apiGet<ComputeBackend[]>("/api/v1/compute-backends?enabled_only=true").catch(() => []),
    ]).then(([usersData, teamsData, backendsData]) => {
      setUsers(usersData.items ?? []);
      setTeams(teamsData.items ?? []);
      setComputeBackends(Array.isArray(backendsData) ? backendsData : []);
    }).finally(() => setLoadingAssignees(false));
  }, []);

  // Available artifacts power the autocomplete + the "not in inventory" warning.
  // Tool-version creation is hard-validated server-side, so flag a mismatch early.
  useEffect(() => {
    const kindParam = toolType === "pypi" ? "wheel" : toolType === "container" ? "docker_image" : "";
    if (!kindParam) return;
    apiGet<ComputeArtifact[]>(`/api/v1/compute-artifacts?kind=${kindParam}&status=available`)
      .then((d) => setArtifacts(Array.isArray(d) ? d : []))
      .catch(() => setArtifacts([]));
  }, [toolType]);

  // name -> available versions/tags, for datalists and the inventory warning.
  const versionsByName = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const a of artifacts) {
      const list = map.get(a.name) ?? [];
      list.push(a.version);
      map.set(a.name, list);
    }
    return map;
  }, [artifacts]);

  const dockerInInventory =
    !dockerImage || (versionsByName.get(dockerImage)?.includes(dockerTag || "latest") ?? false);
  const wheelInInventory =
    !packageName || !packageVersion ||
    (versionsByName.get(packageName)?.includes(packageVersion) ?? false);

  const [sectionsOpen, setSectionsOpen] = useState({
    inputSchema: false,
    outputSchema: false,
    parametersSchema: false,
    resourceRequirements: false,
    changelog: false,
  });
  const [users, setUsers] = useState<{ id: string; email: string; full_name: string | null }[]>([]);
  const [teams, setTeams] = useState<{ slug: string; name: string }[]>([]);
  const [loadingAssignees, setLoadingAssignees] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      let inputSchema: Record<string, unknown> = {};
      let outputSchema: Record<string, unknown> = {};
      let parametersSchema: Record<string, unknown> = {};
      let resourceRequirements: Record<string, unknown> = {};

      try {
        if (inputSchemaJson.trim()) inputSchema = JSON.parse(inputSchemaJson);
        if (outputSchemaJson.trim()) outputSchema = JSON.parse(outputSchemaJson);
        if (parametersSchemaJson.trim()) parametersSchema = JSON.parse(parametersSchemaJson);
        if (resourceRequirementsJson.trim()) resourceRequirements = JSON.parse(resourceRequirementsJson);
      } catch {
        setError("Invalid JSON in one of the schema fields");
        setSaving(false);
        return;
      }

      if (selectedBackend) {
        resourceRequirements = { ...resourceRequirements, backend: selectedBackend };
      } else {
        const { backend: _, ...rest } = resourceRequirements as Record<string, unknown> & { backend?: unknown };
        resourceRequirements = rest;
      }

      const payload: Record<string, unknown> = {
        docker_image: dockerImage || null,
        docker_tag: dockerTag || null,
        input_schema: inputSchema,
        output_schema: outputSchema,
        parameters_schema: parametersSchema,
        resource_requirements: resourceRequirements,
        changelog: changelog || null,
      };

      if (toolType === "pypi") {
        payload.package_name = packageName || null;
        payload.package_version = packageVersion || null;
        payload.entry_point = entryPoint || null;
        payload.package_index_url = packageIndexUrl || null;
      }

      if (toolType === "human") {
        payload.assignment_type = assignmentType || null;
        const assigneeValue = defaultAssignee || null;
        if (assignmentType === "user" && assigneeValue) {
          const user = users.find((u) => u.id === assigneeValue);
          payload.default_assignee = user ? user.email : assigneeValue;
        } else {
          payload.default_assignee = assigneeValue;
        }
        payload.due_in_hours = dueInHours ? parseInt(dueInHours, 10) : null;
        payload.require_attachments = requireAttachments;
        payload.priority = priority || "medium";
        payload.default_project_lead_email = defaultProjectLeadEmail || null;
      }

      if (isEditMode && versionId) {
        await apiPut(`/api/v1/tools/${toolId}/versions/${versionId}/content`, payload);
      } else {
        await apiPost(`/api/v1/tools/${toolId}/versions`, payload);
      }
      onComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : (isEditMode ? "Failed to update version" : "Failed to create version"));
    } finally {
      setSaving(false);
    }
  };

  const titleLabel = kind === "task" ? "Task" : "Tool";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-4xl max-h-[95vh] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {isEditMode ? `${toolName} v${versionNumber}: Update Version` : `${toolName}: New Version`}
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {isEditMode
                ? "Update the content of this version"
                : `Create a new version of this ${titleLabel.toLowerCase()}`}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>

        <div className="space-y-4">
          {toolType === "container" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700">Docker Image</label>
                <input
                  type="text"
                  list="artifact-image-names"
                  value={dockerImage}
                  onChange={(e) => setDockerImage(e.target.value)}
                  placeholder="e.g. python:3.11"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <datalist id="artifact-image-names">
                  {[...versionsByName.keys()].map((n) => (
                    <option key={n} value={n} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Docker Tag</label>
                <input
                  type="text"
                  list="artifact-image-tags"
                  value={dockerTag}
                  onChange={(e) => setDockerTag(e.target.value)}
                  placeholder="e.g. latest, v1.0.0"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <datalist id="artifact-image-tags">
                  {(versionsByName.get(dockerImage) ?? []).map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </div>
              {!dockerInInventory && (
                <p className="text-xs text-amber-600">
                  No published image <span className="font-mono">{dockerImage}:{dockerTag || "latest"}</span> in
                  the artifact inventory. Build &amp; publish it first — saving will be rejected.
                </p>
              )}
            </>
          )}

          {toolType === "human" && (
            <div className="border-t border-gray-200 pt-4 mt-4">
              <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700">Assignment Type</label>
                  <select
                    value={assignmentType}
                    onChange={(e) => setAssignmentType(e.target.value)}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="user">User</option>
                    <option value="team">Team</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Default Assignee</label>
                  <select
                    value={defaultAssignee}
                    onChange={(e) => setDefaultAssignee(e.target.value)}
                    disabled={loadingAssignees}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100"
                  >
                    <option value="">Select {assignmentType === "user" ? "user" : "team"}...</option>
                    {assignmentType === "user"
                      ? users.map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.full_name || u.email}
                          </option>
                        ))
                      : teams.map((t) => (
                          <option key={t.slug} value={t.slug}>
                            {t.name}
                          </option>
                        ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Default Project Lead</label>
                  <select
                    value={users.find(u => u.email === defaultProjectLeadEmail)?.id || ""}
                    onChange={(e) => {
                      const userId = e.target.value;
                      const user = users.find(u => u.id === userId);
                      setDefaultProjectLeadEmail(user ? user.email : "");
                    }}
                    disabled={loadingAssignees}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100"
                  >
                    <option value="">None</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name || u.email}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Priority</label>
                  <select
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Due In (hours)</label>
                  <input
                    type="number"
                    value={dueInHours}
                    onChange={(e) => setDueInHours(e.target.value)}
                    min={1}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div className="flex items-end pb-1">
                  <label className="flex items-center gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={requireAttachments}
                      onChange={(e) => setRequireAttachments(e.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    Require attachments
                  </label>
                </div>
              </div>
            </div>
          )}

          {toolType === "pypi" && (
            <div className="border-t border-gray-200 pt-4 mt-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Package Name</label>
                <input
                  type="text"
                  list="artifact-wheel-names"
                  value={packageName}
                  onChange={(e) => setPackageName(e.target.value)}
                  placeholder="e.g. molecule-property-calculator"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <datalist id="artifact-wheel-names">
                  {[...versionsByName.keys()].map((n) => (
                    <option key={n} value={n} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Package Version</label>
                <input
                  type="text"
                  list="artifact-wheel-versions"
                  value={packageVersion}
                  onChange={(e) => setPackageVersion(e.target.value)}
                  placeholder="e.g. 0.1.0"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <datalist id="artifact-wheel-versions">
                  {(versionsByName.get(packageName) ?? []).map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </div>
              {!wheelInInventory && (
                <p className="text-xs text-amber-600">
                  No published wheel <span className="font-mono">{packageName}=={packageVersion}</span> in
                  the artifact inventory. Build &amp; publish it first — saving will be rejected.
                </p>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700">Entry Point</label>
                <input
                  type="text"
                  value={entryPoint}
                  onChange={(e) => setEntryPoint(e.target.value)}
                  placeholder="e.g. module.submodule:function_name"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Package Index URL (Optional)</label>
                <input
                  type="text"
                  value={packageIndexUrl}
                  onChange={(e) => setPackageIndexUrl(e.target.value)}
                  placeholder="e.g. http://devpi:8080/root/pypi/+simple/"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
          )}

          {(toolType === "api" || !toolType) && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700">Docker Image</label>
                <input
                  type="text"
                  value={dockerImage}
                  onChange={(e) => setDockerImage(e.target.value)}
                  placeholder="e.g. python:3.11"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Docker Tag</label>
                <input
                  type="text"
                  value={dockerTag}
                  onChange={(e) => setDockerTag(e.target.value)}
                  placeholder="e.g. latest, v1.0.0"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </>
          )}

          <AccordionItem
            title="Input Data Schema"
            isOpen={sectionsOpen.inputSchema}
            onToggle={() => setSectionsOpen(s => ({ ...s, inputSchema: !s.inputSchema }))}
          >
            <textarea
              value={inputSchemaJson}
              onChange={(e) => setInputSchemaJson(e.target.value)}
              rows={5}
              placeholder='{"type": "object", "properties": {...}}'
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </AccordionItem>

          <AccordionItem
            title="Output Data Schema"
            isOpen={sectionsOpen.outputSchema}
            onToggle={() => setSectionsOpen(s => ({ ...s, outputSchema: !s.outputSchema }))}
          >
            <textarea
              value={outputSchemaJson}
              onChange={(e) => setOutputSchemaJson(e.target.value)}
              rows={5}
              placeholder='{"type": "object", "properties": {...}}'
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </AccordionItem>

          <AccordionItem
            title="Tool Parameters Schema"
            isOpen={sectionsOpen.parametersSchema}
            onToggle={() => setSectionsOpen(s => ({ ...s, parametersSchema: !s.parametersSchema }))}
          >
            <textarea
              value={parametersSchemaJson}
              onChange={(e) => setParametersSchemaJson(e.target.value)}
              rows={5}
              placeholder='{"type": "object", "properties": {...}}'
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </AccordionItem>

          {toolType !== "pypi" && toolType !== "human" && (
            <AccordionItem
              title="Resource Requirements"
              isOpen={sectionsOpen.resourceRequirements}
              onToggle={() => setSectionsOpen(s => ({ ...s, resourceRequirements: !s.resourceRequirements }))}
            >
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Compute Backend</label>
                  <select
                    value={selectedBackend}
                    onChange={(e) => setSelectedBackend(e.target.value)}
                    className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="">Default (Docker)</option>
                    {computeBackends.map((b) => (
                      <option key={b.name} value={b.name}>{b.display_name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Additional Requirements (JSON)</label>
                  <textarea
                    value={resourceRequirementsJson}
                    onChange={(e) => setResourceRequirementsJson(e.target.value)}
                    rows={3}
                    placeholder='{"cpu": "2", "memory": "4Gi"}'
                    className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>
            </AccordionItem>
          )}

          <AccordionItem
            title="Changelog"
            isOpen={sectionsOpen.changelog}
            onToggle={() => setSectionsOpen(s => ({ ...s, changelog: !s.changelog }))}
          >
            <textarea
              value={changelog}
              onChange={(e) => setChangelog(e.target.value)}
              rows={4}
              placeholder="What changed in this version — e.g. 'Added BBB endpoint', 'Fixed LogP calc for charged species'"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </AccordionItem>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        <div className="mt-4 flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? (isEditMode ? "Saving..." : "Creating...") : (isEditMode ? "Save Changes" : "Create Version")}
          </button>
          <button
            onClick={onClose}
            className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
