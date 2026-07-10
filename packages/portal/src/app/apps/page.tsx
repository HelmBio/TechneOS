"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, type AppRecord, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLabel } from "@/lib/labels";
import { AppIcon } from "@/components/app-icon";
import { NewResourceButton } from "@/components/new-resource-button";
import { hasPermission } from "@/lib/rbac";

const CATEGORIES = ["all", "visualization", "notebook", "editor", "data-browser", "ml-playground", "general"];

const RUNTIME_COLORS: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-700",
  building: "bg-amber-100 text-amber-700",
  deploying: "bg-amber-100 text-amber-700",
  pending: "bg-gray-100 text-gray-600",
  failed: "bg-red-100 text-red-700",
  stopped: "bg-gray-200 text-gray-700",
};

export default function AppsPage() {
  const appsLabel = useLabel("resource.app.plural");
  const { user, loading: authLoading } = useAuth();
  const [apps, setApps] = useState<AppRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");

  useEffect(() => {
    if (authLoading || !user) return;
    const params: Record<string, string> = { skip: "0", limit: "50" };
    if (search) params.q = search;
    if (category !== "all") params.category = category;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<AppRecord>>("/api/v1/apps", params);
        setApps(data.items);
        setTotal(data.total);
      } catch {
        setApps([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, search, category]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please <a href="/login" className="text-blue-600 underline">log in</a> to view apps.
      </p>
    );

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{appsLabel}</h1>
          {total > 0 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {total}
            </span>
          )}
        </div>
        {hasPermission(user.permissions || [], "app", "create", "*") && (
          <NewResourceButton href="/apps/new" tooltip="Register a new interactive web application" />
        )}
      </div>

      {total > 10 && (
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <input
            type="text"
            placeholder="Search apps..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="block w-full max-w-md rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <div className="flex gap-1 flex-wrap">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
                  category === cat
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : apps.length === 0 ? (
        <p className="mt-6 text-gray-500">No apps registered yet.</p>
      ) : (
        <div className="mt-6 grid gap-6 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {apps.map((a) => {
            const launchable =
              (a.launch_mode === "external" && a.status === "active") ||
              (a.launch_mode === "embedded" && a.runtime_status === "active");
            return (
              <div
                key={a.id}
                className="relative flex flex-col rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md"
              >
                <Link
                  href={`/apps/${a.slug}`}
                  aria-label={a.name}
                  className="absolute inset-0 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <div className="flex items-start gap-3">
                  <AppIcon iconUrl={a.icon_url} name={a.name} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-blue-600">{a.name}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-gray-600">{a.description}</p>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 capitalize text-gray-700">
                    {a.category}
                  </span>
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 capitalize text-indigo-700">
                    {a.launch_mode}
                  </span>
                  {a.launch_mode === "embedded" && (
                    <span
                      className={`rounded-full px-2 py-0.5 capitalize ${
                        RUNTIME_COLORS[a.runtime_status] || "bg-gray-100 text-gray-700"
                      }`}
                    >
                      {a.runtime_status}
                    </span>
                  )}
                </div>
                {launchable && (
                  <Link
                    href={`/apps/${a.slug}/launch`}
                    className="relative mt-4 flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5" />
                      <path d="M15 3h6v6" />
                      <path d="m10 14 11-11" />
                    </svg>
                    Launch App
                  </Link>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
