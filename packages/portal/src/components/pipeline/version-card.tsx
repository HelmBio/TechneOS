"use client";

import { useState } from "react";
import type { PipelineVersion, PipelineStepConfig } from "@/lib/api";
import { STATUS_COLORS, definitionEditable, nextStatusOptions } from "@/lib/version-lifecycle";

// Statuses for which a version can be run.
const RUNNABLE_VERSION_STATUSES = new Set(["active", "testing"]);

export function PipelineVersionCard({
  version,
  canUpdate,
  onStatusChange,
  onStartRun,
  onUpdateVersion,
}: {
  version: PipelineVersion;
  pipelineId: string;
  canUpdate: boolean;
  onStatusChange: (versionId: string, status: string) => void;
  onStartRun?: (versionId: string) => void;
  onUpdateVersion?: (versionId: string) => void;
}) {
  const [expanded, setExpanded] = useState(version.status === "active");
  const [showChangelog, setShowChangelog] = useState(false);
  const statuses = nextStatusOptions(version.status);
  const steps = (version.steps ?? []) as unknown as PipelineStepConfig[];

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
          {RUNNABLE_VERSION_STATUSES.has(version.status) && onStartRun && (
            <div
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); onStartRun(version.id); }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onStartRun(version.id);
                }
              }}
              className="group relative rounded border border-green-200 bg-green-50 p-1.5 text-green-600 hover:bg-green-100 hover:text-green-700 cursor-pointer"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
              <span className="pointer-events-none absolute top-full left-0 mt-1 w-max max-w-[120px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                Start a new run
              </span>
            </div>
          )}
          {canUpdate && onUpdateVersion && definitionEditable(version.status, version.has_runs) && (
            <div
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); onUpdateVersion(version.id); }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onUpdateVersion(version.id);
                }
              }}
              className="group relative rounded border border-blue-200 bg-blue-50 p-1.5 text-blue-600 hover:bg-blue-100 hover:text-blue-700 cursor-pointer"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
              <span className="pointer-events-none absolute top-full left-0 mt-1 w-max max-w-[120px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                Update this version
              </span>
            </div>
          )}
        </div>
        <span className="text-sm text-gray-500">
          {version.updated_by_name || version.creator_name || version.updated_by || version.created_by} ·{" "}
          {new Date(version.updated_at || version.created_at).toLocaleDateString()}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-4 space-y-4">
          {/* The DAG graph lives at the pipeline level. A version card
              shows only its bindings — the tool version pinned at each step and
              the parameter values used. */}
          {steps.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">
                Bindings <span className="font-normal text-gray-400">(tool pins &amp; parameters)</span>
              </h4>
              <div className="space-y-2">
                {steps.map((step, idx) => (
                  <div key={step.name} className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-[10px] font-bold text-blue-700">
                          {idx + 1}
                        </span>
                        <span className="text-sm font-medium text-gray-900">{step.name}</span>
                      </div>
                      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-mono text-gray-600">
                        {step.tool_slug}
                        {step.tool_version != null ? `:v${step.tool_version}` : ":latest"}
                      </span>
                    </div>
                    {Object.keys(step.parameters).length > 0 ? (
                      <pre className="mt-1 max-h-24 overflow-auto rounded bg-white p-2 text-[11px] border border-gray-100">
                        {JSON.stringify(step.parameters, null, 2)}
                      </pre>
                    ) : (
                      <p className="mt-1 text-[11px] text-gray-400">default parameters</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* v1's changelog is auto-set to "Initial version" boilerplate — hide it. */}
          {version.version > 1 && version.changelog && (
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
        </div>
      )}
    </div>
  );
}
