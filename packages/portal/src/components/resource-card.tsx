"use client";

import Link from "next/link";
import { Fragment, type ReactNode } from "react";
import { FollowIconButton } from "@/components/follow-icon-button";

interface MetadataItem {
  label: string;
  value: ReactNode;
}

interface ResourceCardProps {
  name: string;
  href: string;
  description?: string | null;
  tags: string[];
  metadata: MetadataItem[];
  badges?: ReactNode;
  isFollowed: boolean;
  onToggleFollow: () => void;
}

export function ResourceCard({ name, href, description, tags, metadata, badges, isFollowed, onToggleFollow }: ResourceCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center gap-1.5">
        <Link href={href} className="font-medium text-blue-600 hover:underline">
          {name}
        </Link>
        <FollowIconButton followed={isFollowed} onClick={onToggleFollow} />
      </div>
      {description && <p className="mt-1 text-xs text-gray-500 line-clamp-2">{description}</p>}
      {tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {tags.slice(0, 3).map((tag) => (
            <span key={tag} className="rounded bg-gray-50 px-1.5 py-0.5 text-[10px] text-gray-500">{tag}</span>
          ))}
          {tags.length > 3 && <span className="text-[10px] text-gray-400">+{tags.length - 3}</span>}
        </div>
      )}
      <div className="mt-2 grid grid-cols-[80px_1fr] gap-1 text-xs">
        {metadata.map((item, i) => (
          <Fragment key={i}>
            <p className="font-medium text-gray-500">{item.label}</p>
            <p className="text-gray-900">{item.value}</p>
          </Fragment>
        ))}
      </div>
      {badges && <div className="mt-2 flex flex-wrap gap-2">{badges}</div>}
    </div>
  );
}
