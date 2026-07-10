"use client";

import type { ReactNode } from "react";

interface DetailMetadataProps {
  description?: string | null;
  creatorName?: string | null;
  createdAt: string;
  updatedByName?: string | null;
  updatedAt?: string | null;
  tags: string[];
  isPublic?: boolean;
  orgName?: string | null;
  /** Type-specific pill(s) shown after the tags (e.g. tool_type / pipeline_type). */
  badges?: ReactNode;
}

export function DetailMetadata({
  description,
  creatorName,
  createdAt,
  updatedByName,
  updatedAt,
  tags,
  isPublic,
  orgName,
  badges,
}: DetailMetadataProps) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm text-sm space-y-2">
      {description && (
        <p className="text-gray-600">{description}</p>
      )}
      <p className="text-gray-600 italic">
        Created by <span className="font-medium text-gray-900">{creatorName || "—"}</span> on{" "}
        {new Date(createdAt).toLocaleDateString()}
        {updatedAt && updatedByName && (
          <>; Updated by <span className="font-medium text-gray-900">{updatedByName}</span> on{" "}
            {new Date(updatedAt).toLocaleDateString()}</>
        )}
        .
      </p>
      <div className="flex gap-1.5 flex-wrap items-center">
        {tags.map((tag) => (
          <span key={tag} className="rounded bg-gray-50 px-2 py-0.5 text-sm text-gray-500">{tag}</span>
        ))}
        {isPublic && (
          <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-sm font-medium text-green-800">Public</span>
        )}
        {orgName && (
          <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-sm font-medium text-gray-700">{orgName}</span>
        )}
        {badges}
      </div>
    </section>
  );
}
