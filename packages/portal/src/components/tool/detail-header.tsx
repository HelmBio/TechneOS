"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { FollowIconButton } from "@/components/follow-icon-button";

interface DetailHeaderProps {
  name: string;
  kind: "tool" | "task" | "pipeline";
  isFollowed: boolean;
  subLoading?: boolean;
  onToggleFollow: () => void;
  onEdit?: () => void;
  onExport?: () => void;
  actions?: ReactNode;
  breadcrumbLabel?: string;
  /** Override the breadcrumb root link text (e.g. a customizable resource label). */
  breadcrumbRootLabel?: string;
}

const LIST_HREF: Record<DetailHeaderProps["kind"], string> = {
  tool: "/tools",
  task: "/tasks",
  pipeline: "/pipelines",
};

const ROOT_LABEL: Record<DetailHeaderProps["kind"], string> = {
  tool: "Tools",
  task: "Tasks",
  pipeline: "Pipelines",
};

export function DetailHeader({ name, kind, isFollowed, subLoading = false, onToggleFollow, onEdit, onExport, actions, breadcrumbLabel, breadcrumbRootLabel }: DetailHeaderProps) {
  const listHref = LIST_HREF[kind];
  const label = kind;

  return (
    <div className="flex items-start justify-between">
      <div>
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
          <Link href={listHref} className="hover:text-blue-600">
            {breadcrumbRootLabel || ROOT_LABEL[kind]}
          </Link>
          <span>/</span>
          <span>{breadcrumbLabel || name}</span>
        </div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{name}</h1>
          <FollowIconButton
            followed={isFollowed}
            loading={subLoading}
            onClick={onToggleFollow}
            placement="below"
          />
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {onEdit && (
          <div className="relative group inline-flex">
            <button
              onClick={onEdit}
              aria-label={`Update ${label} definition`}
              className="rounded-full p-1.5 text-gray-400 hover:bg-blue-50 hover:text-blue-600 transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <span className="pointer-events-none absolute z-50 w-max max-w-[200px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100 top-full right-0 mt-1">
              Update {label} definition
            </span>
          </div>
        )}
        {onExport && (
          <div className="relative group inline-flex">
            <button
              onClick={onExport}
              className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 transition-colors"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M16 18l6-6-6-6" />
                <path d="M8 6l-6 6 6 6" />
              </svg>
            </button>
            <span className="pointer-events-none absolute z-50 w-max max-w-[150px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100 top-full right-0 mt-1">
              Export {label} definition as JSON
            </span>
          </div>
        )}
        {actions}
      </div>
    </div>
  );
}
