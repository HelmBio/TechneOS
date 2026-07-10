"use client";

import { useState } from "react";
import type { ToolVersion } from "@/lib/api";
import { VersionCard } from "@/components/tool/version-card";

interface DetailVersionsSectionProps {
  versions: ToolVersion[];
  canCreateVersion: boolean;
  canUpdate: boolean;
  toolSlug: string;
  toolType: string;
  toolId: string;
  statusUpdating: string | null;
  onAddVersion: () => void;
  onUpdateVersion: (versionId: string) => void;
  onStatusChange: (versionId: string, status: string) => void;
  onStartRunVersion?: (versionId: string) => void;
}

export function DetailVersionsSection({
  versions,
  canCreateVersion,
  canUpdate,
  toolSlug,
  toolType,
  toolId,
  statusUpdating,
  onAddVersion,
  onUpdateVersion,
  onStatusChange,
  onStartRunVersion,
}: DetailVersionsSectionProps) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(!open); } }}
        className="flex w-full cursor-pointer items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-900">Versions</span>
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">{versions.length}</span>
          {canCreateVersion && (
            <div className="relative group inline-flex">
              <button
                onClick={(e) => { e.stopPropagation(); onAddVersion(); }}
                className="rounded px-2.5 py-1.5 text-blue-600 bg-blue-50 hover:bg-blue-100 hover:text-blue-700 transition-colors"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </button>
              <span className="pointer-events-none absolute z-50 w-max max-w-[160px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100 top-full right-0 mt-1">
                Add a new version
              </span>
            </div>
          )}
        </div>
        <svg
          className={`h-4 w-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          {versions.map((v) => (
            <VersionCard
              key={v.id}
              version={v}
              toolId={toolId}
              toolSlug={toolSlug}
              toolType={toolType}
              onStatusChange={onStatusChange}
              onUpdateVersion={onUpdateVersion}
              canUpdate={canUpdate}
              onStartRun={onStartRunVersion}
            />
          ))}
          {versions.length === 0 && (
            <p className="text-sm text-gray-500">No versions yet.</p>
          )}
          {statusUpdating && (
            <p className="text-xs text-gray-400">Updating status...</p>
          )}
        </div>
      )}
    </div>
  );
}
