"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/rbac";
import { NotificationBell } from "@/components/notifications";
import { apiGet, type Org } from "@/lib/api";
import { useCollectionCounts, type Collection } from "@/lib/use-collection-counts";
import { useLabels } from "@/lib/labels";
import type { LabelKey } from "@/lib/labels";
import { siteConfig } from "@/lib/site-config";
import {
  ToolIcon,
  TaskIcon,
  PipelineIcon,
  AgentIcon,
  AppIcon,
  DatasetIcon,
  ToolRunIcon,
  TaskRunIcon,
  PipelineRunIcon,
  AgenticRunIcon,
} from "@/components/icons";
import { useEffect, useRef, useState } from "react";

const NAV_ITEMS: {
  href: string;
  labelKey: LabelKey;
  icon: React.ReactNode;
  countKey?: Collection;
}[] = [
  {
    href: "/tools",
    labelKey: "resource.tool.plural",
    countKey: "tools",
    icon: <ToolIcon className="h-5 w-5" />,
  },
  {
    href: "/tasks",
    labelKey: "resource.task.plural",
    countKey: "tasks",
    icon: <TaskIcon className="h-5 w-5" />,
  },
  {
    href: "/pipelines",
    labelKey: "resource.pipeline.plural",
    countKey: "pipelines",
    icon: <PipelineIcon className="h-5 w-5" />,
  },
  {
    href: "/agents",
    labelKey: "resource.agent.plural",
    countKey: "agents",
    icon: <AgentIcon className="h-5 w-5" />,
  },
  {
    href: "/apps",
    labelKey: "resource.app.plural",
    countKey: "apps",
    icon: <AppIcon className="h-5 w-5" />,
  },
  {
    href: "/datasets",
    labelKey: "resource.dataset.plural",
    countKey: "datasets",
    icon: <DatasetIcon className="h-5 w-5" />,
  },
];

/** Molecule/flask TechneOS icon */
function TechneOSIcon({ className = "h-8 w-8" }: { className?: string }) {
  // Brand artwork lives in siteConfig so the navbar and the favicon share one
  // source. The markup uses currentColor; this <svg> inherits it from the
  // className's text color.
  return (
    <svg
      className={className}
      viewBox={siteConfig.icon.viewBox}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      dangerouslySetInnerHTML={{ __html: siteConfig.icon.inner }}
    />
  );
}

/** Top bar with logo/title on the left, notifications + profile on the right */
export function TopBar() {
  const { user, role, logout } = useAuth();
  const pathname = usePathname();
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const [orgName, setOrgName] = useState<string | null>(null);

  useEffect(() => {
    if (user?.org_id) {
      apiGet<Org>(`/api/v1/orgs/${user.org_id}`)
        .then((org) => setOrgName(org.name))
        .catch(() => setOrgName(null));
    }
  }, [user?.org_id]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false);
      }
    }
    if (profileOpen) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [profileOpen]);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4">
      {/* Left: icon + title + tagline */}
      <Link href="/" className="flex items-center gap-2">
        <TechneOSIcon className="h-8 w-8 text-indigo-600" />
        <span className="text-base font-bold text-gray-900">{siteConfig.name}</span>
        <span className="hidden text-sm text-gray-400 md:inline">— {siteConfig.tagline}</span>
      </Link>

      {/* Right: notifications + profile */}
      <div className="flex items-center gap-3">
        {user ? (
          <>
            <Link
              href="/assistant"
              title="Ask Assistant"
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm transition ${
                pathname === "/assistant"
                  ? "bg-indigo-50 font-medium text-indigo-700"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              }`}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
              </svg>
              <span>Assistant</span>
            </Link>
            <NotificationBell />
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setProfileOpen((o) => !o)}
                className="flex items-center gap-2 rounded-full border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-xs font-medium text-indigo-700">
                  {user.full_name?.charAt(0)?.toUpperCase() || user.email.charAt(0).toUpperCase()}
                </span>
                <span className="max-w-[160px] truncate">{user.full_name || user.email}</span>
                <svg
                  className={`h-4 w-4 text-gray-400 transition-transform ${profileOpen ? "rotate-180" : ""}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {profileOpen && (
                <div className="absolute right-0 z-50 mt-1 w-72 rounded-lg border border-gray-200 bg-white shadow-lg">
                  <div className="border-b border-gray-100 px-4 py-3 space-y-2.5">
                    {/* Name */}
                    <div className="flex items-center gap-2.5">
                      <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                      </svg>
                      <span className="text-sm font-medium text-gray-900 truncate">{user.full_name || "User"}</span>
                    </div>
                    {/* Email */}
                    <div className="flex items-center gap-2.5">
                      <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
                      </svg>
                      <span className="text-xs text-gray-500 truncate">{user.email}</span>
                    </div>
                    {/* Role */}
                    {role && (
                      <div className="flex items-center gap-2.5">
                        <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                        </svg>
                        <span className="inline-block rounded bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">{role}</span>
                      </div>
                    )}
                    {/* Organization */}
                    {orgName && (
                      <div className="flex items-center gap-2.5">
                        <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />
                        </svg>
                        <span className="text-xs text-gray-500 truncate">{orgName}</span>
                      </div>
                    )}
                  </div>
                  <div className="py-1">
                    {user.auth_method === "local" && (
                      <Link
                        href="/settings/password"
                        onClick={() => setProfileOpen(false)}
                        className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                        </svg>
                        Change Password
                      </Link>
                    )}
                    <Link
                      href="/settings/notifications"
                      onClick={() => setProfileOpen(false)}
                      className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    >
                      <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
                      </svg>
                      Notification Settings
                    </Link>
                    {role === "platform_admin" && (
                      <Link
                        href="/settings/labels"
                        onClick={() => setProfileOpen(false)}
                        className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                      >
                        <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h.008v.008H6V6z" />
                        </svg>
                        Label Settings
                      </Link>
                    )}
                    <button
                      onClick={() => {
                        setProfileOpen(false);
                        logout();
                      }}
                      className="flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    >
                      <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                      </svg>
                      Sign out
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <Link href="/login" className="text-sm text-blue-600 hover:text-blue-800">
            Login
          </Link>
        )}
      </div>
    </header>
  );
}

/** Collapsible vertical sidebar with navigation only */
export function Sidebar() {
  const { user, permissions, role } = useAuth();
  const { t } = useLabels();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const counts = useCollectionCounts();

  const hasPlatformScope = hasPermission(permissions, "*", "*", "platform");
  const showOrgAdmin = user && hasPermission(permissions, "org", "update", "org") && !hasPlatformScope;
  const isPlatformAdmin = role === "platform_admin";

  if (!user) {
    return null;
  }

  return (
    <aside
      className={`flex h-full flex-col border-r border-gray-200 bg-white transition-all duration-200 ${
        collapsed ? "w-14" : "w-52"
      }`}
    >
      {/* Collapse toggle */}
      <div className="flex items-center justify-between px-2 py-2">
        {!collapsed && <span className="px-3 text-[10px] font-semibold uppercase tracking-wider text-gray-400">{t("section.catalog")}</span>}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            {collapsed ? (
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
            ) : (
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7M19 19l-7-7 7-7" />
            )}
          </svg>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2">
        <ul className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const count = item.countKey != null ? counts[item.countKey] : null;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  title={collapsed ? t(item.labelKey) : undefined}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                    active
                      ? "bg-indigo-50 font-medium text-indigo-700"
                      : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                  } ${collapsed ? "justify-center" : ""}`}
                >
                  {item.icon}
                  {!collapsed && (
                    <>
                      <span className="flex-1">{t(item.labelKey)}</span>
                      {count != null && (
                        <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs tabular-nums text-gray-500">
                          {count}
                        </span>
                      )}
                    </>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>

        {/* Runs */}
        <div className="mt-4 border-t border-gray-200 pt-3">
          {!collapsed && <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">{t("section.executions")}</p>}
          <Link
            href="/tool-runs"
            title={collapsed ? t("exec.tool.plural") : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
              pathname.startsWith("/tool-runs")
                ? "bg-indigo-50 font-medium text-indigo-700"
                : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
            } ${collapsed ? "justify-center" : ""}`}
          >
            <ToolRunIcon className="h-5 w-5" />
            {!collapsed && (
              <>
                <span className="flex-1">{t("exec.tool.plural")}</span>
                {counts["tool-runs"] != null && (
                  <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs tabular-nums text-gray-500">
                    {counts["tool-runs"]}
                  </span>
                )}
              </>
            )}
          </Link>
          <Link
            href="/task-runs"
          title={collapsed ? t("exec.task.plural") : undefined}
          className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
            pathname.startsWith("/task-runs")
              ? "bg-indigo-50 font-medium text-indigo-700"
              : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
          } ${collapsed ? "justify-center" : ""}`}
        >
          <TaskRunIcon className="h-5 w-5" />
          {!collapsed && (
              <>
                <span className="flex-1">{t("exec.task.plural")}</span>
                {counts["task_runs"] != null && (
                  <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs tabular-nums text-gray-500">
                    {counts["task_runs"]}
                  </span>
                )}
              </>
            )}
        </Link>
          <Link
            href="/pipeline-runs"
            title={collapsed ? t("exec.pipeline.plural") : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
              pathname.startsWith("/pipeline-runs")
                ? "bg-indigo-50 font-medium text-indigo-700"
                : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
            } ${collapsed ? "justify-center" : ""}`}
          >
            <PipelineRunIcon className="h-5 w-5" />
            {!collapsed && (
              <>
                <span className="flex-1">{t("exec.pipeline.plural")}</span>
                {counts["pipeline-runs"] != null && (
                  <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs tabular-nums text-gray-500">
                    {counts["pipeline-runs"]}
                  </span>
                )}
              </>
            )}
          </Link>
          <Link
            href="/agentic-runs"
          title={collapsed ? t("exec.agent.plural") : undefined}
          className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
            pathname.startsWith("/agentic-runs")
              ? "bg-indigo-50 font-medium text-indigo-700"
              : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
          } ${collapsed ? "justify-center" : ""}`}
        >
          <AgenticRunIcon className="h-5 w-5" />
          {!collapsed && (
              <>
                <span className="flex-1">{t("exec.agent.plural")}</span>
                {counts["agentic-runs"] != null && (
                  <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-xs tabular-nums text-gray-500">
                    {counts["agentic-runs"]}
                  </span>
                )}
              </>
            )}
        </Link>
        </div>
      </nav>

      {/* Admin links */}
      <div className="border-t border-gray-200 px-2 py-2">
        {showOrgAdmin && (
          <Link
            href="/org-admin"
            title={collapsed ? "Admin" : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
              pathname.startsWith("/org-admin")
                ? "bg-indigo-50 font-medium text-indigo-700"
                : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
            } ${collapsed ? "justify-center" : ""}`}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 0 0 3.741-.479 3 3 0 0 0-4.682-2.72m.94 3.198.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0 1 12 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 0 1 6 18.719m12 0a5.971 5.971 0 0 0-.941-3.197m0 0A5.995 5.995 0 0 0 12 12.75a5.995 5.995 0 0 0-5.058 2.772m0 0a3 3 0 0 0-4.681 2.72 8.986 8.986 0 0 0 3.74.477m.94-3.197a5.971 5.971 0 0 0-.94 3.197M15 6.75a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm6 3a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm-13.5 0a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Z" />
            </svg>
            {!collapsed && <span>Admin</span>}
          </Link>
        )}
        {isPlatformAdmin && (
          <Link
            href="/admin"
            title={collapsed ? "Admin" : undefined}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
              pathname.startsWith("/admin")
                ? "bg-indigo-50 font-medium text-indigo-700"
                : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
            } ${collapsed ? "justify-center" : ""}`}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
            </svg>
            {!collapsed && <span>Admin</span>}
          </Link>
        )}
      </div>
    </aside>
  );
}

// Keep backward-compatible export name
export { Sidebar as Navbar };
