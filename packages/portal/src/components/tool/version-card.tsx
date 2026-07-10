"use client";

import { useState } from "react";
import type { ToolVersion } from "@/lib/api";
import {
  STATUS_COLORS,
  definitionEditable,
  nextStatusOptions,
} from "@/lib/version-lifecycle";

export { STATUS_COLORS };

function SchemaViewer({ label, schema }: { label: string; schema: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  if (!schema || Object.keys(schema).length === 0) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="text-sm text-blue-600 hover:underline"
      >
        {open ? "Hide" : "Show"} {label}
      </button>
      {open && (
        <pre className="mt-1 max-h-60 overflow-auto rounded bg-gray-50 p-3 text-xs">
          {JSON.stringify(schema, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function VersionCard({
  version,
  toolSlug,
  toolType,
  onStatusChange,
  onUpdateVersion,
  canUpdate,
  onStartRun,
}: {
  version: ToolVersion;
  toolId: string;
  toolSlug: string;
  toolType: string;
  onStatusChange: (versionId: string, status: string) => void;
  onUpdateVersion: (versionId: string) => void;
  canUpdate: boolean;
  onStartRun?: (versionId: string) => void;
}) {
  const [expanded, setExpanded] = useState(version.status === "active");
  const [showChangelog, setShowChangelog] = useState(false);
  const statuses = nextStatusOptions(version.status);

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
      >
        <div className="flex items-center gap-3">
          <svg
            className={`h-4 w-4 text-gray-400 transition-transform ${expanded ? "rotate-90" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="font-medium text-gray-900">v{version.version}</span>
          {canUpdate ? (
            <select
              value={version.status}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                e.stopPropagation();
                onStatusChange(version.id, e.target.value);
              }}
              className={`rounded-full px-2 py-0.5 text-xs font-medium border-0 cursor-pointer ${STATUS_COLORS[version.status] || "bg-gray-100"}`}
            >
              {statuses.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          ) : (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[version.status] || "bg-gray-100"}`}>
              {version.status}
            </span>
          )}
          {(version.status === "active" || version.status === "testing") && onStartRun && (
            <div
              onClick={(e) => { e.stopPropagation(); onStartRun(version.id); }}
              className="group relative rounded border border-green-200 bg-green-50 p-1.5 text-green-600 hover:bg-green-100 hover:text-green-700 cursor-pointer"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
              <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[120px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                Start a new run
              </span>
            </div>
          )}
          {canUpdate && definitionEditable(version.status, version.has_runs) && (
            <div
              onClick={(e) => { e.stopPropagation(); onUpdateVersion(version.id); }}
              className="group relative rounded border border-blue-200 bg-blue-50 p-1.5 text-blue-600 hover:bg-blue-100 hover:text-blue-700 cursor-pointer"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
              <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[100px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                Update version
              </span>
            </div>
          )}
        </div>
        <span className="text-sm text-gray-500">
          {version.updated_by_name || version.creator_name || version.updated_by || version.created_by} · {version.updated_at ? new Date(version.updated_at).toLocaleDateString() : new Date(version.created_at).toLocaleDateString()}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-4 space-y-4">
          {(toolType === "container" || toolType === "api" || !toolType) && version.docker_image && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-1">Docker Image</h4>
              <code className="block rounded bg-gray-50 px-3 py-1.5 text-sm">
                {version.docker_image}:{version.docker_tag || "latest"}
              </code>
            </div>
          )}

          {toolType === "pypi" && version.package_name && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-1">Package</h4>
              <code className="block rounded bg-gray-50 px-3 py-1.5 text-sm">
                {version.package_name + ' == ' + version.package_version}
              </code>
              <h4 className="text-sm font-medium text-gray-700 mt-2 mb-1">Entry Point</h4>
              <code className="block rounded bg-gray-50 px-3 py-1.5 text-sm">
                {version.entry_point}
              </code>
              {version.package_index_url && (
                <>
                  <h4 className="text-sm font-medium text-gray-700 mt-2 mb-1">Package Index</h4>
                  <code className="block rounded bg-gray-50 px-3 py-1.5 text-sm">
                    {version.package_index_url}
                  </code>
                </>
              )}
            </div>
          )}

          {toolType === "human" && version.assignment_type && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-1">Assignment Config</h4>
              <div className="flex flex-wrap gap-2">
                <span className="rounded bg-gray-50 px-2 py-1 text-xs">
                  Type: {version.assignment_type}
                </span>
                {version.default_assignee && (
                  <span className="rounded bg-gray-50 px-2 py-1 text-xs">
                    Assignee: {version.default_assignee}
                  </span>
                )}
                {version.due_in_hours != null && (
                  <span className="rounded bg-gray-50 px-2 py-1 text-xs">
                    Due in: {version.due_in_hours}h
                  </span>
                )}
                {version.require_attachments && (
                  <span className="rounded bg-gray-50 px-2 py-1 text-xs">
                    Attachments required
                  </span>
                )}
                {version.default_project_lead_email && (
                  <span className="rounded bg-gray-50 px-2 py-1 text-xs">
                    Project Lead: {version.default_project_lead_email}
                  </span>
                )}
                {version.priority && (
                  <span className="rounded bg-gray-50 px-2 py-1 text-xs">
                    Priority: {version.priority}
                  </span>
                )}
              </div>
            </div>
          )}

          {toolType !== "pypi" && version.resource_requirements && Object.keys(version.resource_requirements).length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-1">Resource Requirements</h4>
              <div className="flex flex-wrap gap-2">
                {(version.resource_requirements as Record<string, unknown>)?.backend != null && (
                  <span className="rounded-full bg-blue-100 text-blue-800 px-2.5 py-0.5 text-xs font-medium">
                    {String((version.resource_requirements as Record<string, unknown>).backend)}
                  </span>
                )}
                {Object.entries(version.resource_requirements)
                  .filter(([k]) => k !== "backend" && k !== "backend_config")
                  .map(([k, v]) => (
                  <span key={k} className="rounded bg-gray-50 px-2 py-1 text-xs">
                    {k}: {String(v)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {version.changelog && (
            <div>
              <button
                onClick={() => setShowChangelog(!showChangelog)}
                className="text-sm text-blue-600 hover:underline"
              >
                {showChangelog ? "Hide" : "Show"} changelog
              </button>
              {showChangelog && (
                <pre className="mt-2 max-h-80 overflow-auto rounded bg-gray-900 p-4 text-sm text-green-300">
                  {version.changelog}
                </pre>
              )}
            </div>
          )}

          <SchemaViewer label="Input Data Schema" schema={version.input_schema} />
          <SchemaViewer label="Output Data Schema" schema={version.output_schema} />
          <SchemaViewer label="Tool Parameters Schema" schema={version.parameters_schema} />

        </div>
      )}
    </div>
  );
}
