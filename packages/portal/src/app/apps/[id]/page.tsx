"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { useParams, useRouter } from "next/navigation";
import {
  apiGet,
  apiPost,
  type AppLaunchRecord,
  type AppLaunchResult,
  type AppRecord,
  type PaginatedResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

const ADMIN_ROLES = new Set(["platform_admin", "org_admin"]);

export default function AppDetailPage() {
  const appsLabel = useLabel("resource.app.plural");
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { role, loading: authLoading } = useAuth();
  const [app, setApp] = useState<AppRecord | null>(null);
  const [launches, setLaunches] = useState<AppLaunchRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = role !== null && ADMIN_ROLES.has(role);

  const refresh = () => {
    apiGet<AppRecord>(`/api/v1/apps/${params.id}`)
      .then(setApp)
      .catch(() => setApp(null));
    apiGet<PaginatedResponse<AppLaunchRecord>>(`/api/v1/apps/${params.id}/launches`, { limit: "10" })
      .then((d) => setLaunches(d.items))
      .catch(() => setLaunches([]));
  };

  useEffect(() => {
    if (!params.id) return;
    if (!authLoading && !isAdmin) return;
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id, authLoading, isAdmin]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading…</p>;

  if (!isAdmin) {
    return (
      <div className="space-y-3 p-8">
        <h1 className="text-2xl font-bold text-gray-900">Access denied</h1>
        <p className="text-gray-600">
          App details are only available to platform admins and organization admins.
        </p>
        <Link href="/apps" className="inline-block text-sm text-blue-600 hover:underline">
          ← Back to {appsLabel}
        </Link>
      </div>
    );
  }

  if (!app) return <p className="p-8 text-gray-500">Loading…</p>;

  const handleLaunch = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiPost<AppLaunchResult>(`/api/v1/apps/${app.id}/launch`, {});
      if (r.launch_mode === "external") {
        window.open(r.launch_url, "_blank", "noopener,noreferrer");
      } else {
        router.push(`/apps/${app.id}/launch`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleDeploy = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/v1/apps/${app.id}/deploy`, {});
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/v1/apps/${app.id}/stop`, {});
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const launchable =
    app.launch_mode === "external" ||
    (app.launch_mode === "embedded" && app.runtime_status === "active");

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        {app.icon_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={app.icon_url} alt="" className="h-16 w-16 rounded-lg object-cover" />
        ) : (
          <div className="flex h-16 w-16 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
            <span className="text-2xl font-semibold">{app.name.charAt(0)}</span>
          </div>
        )}
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">{app.name}</h1>
          <p className="mt-1 text-gray-600">{app.description}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-gray-100 px-2 py-0.5 capitalize text-gray-700">
              {app.category}
            </span>
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 capitalize text-indigo-700">
              {app.launch_mode}
            </span>
            {app.launch_mode === "embedded" && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 capitalize text-gray-700">
                runtime: {app.runtime_status}
              </span>
            )}
            <span className="rounded-full bg-gray-100 px-2 py-0.5 capitalize text-gray-700">
              auth: {app.auth_mode}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <div className="group relative inline-flex">
            <button
              onClick={handleLaunch}
              disabled={busy || !launchable}
              className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5" />
                <path d="M15 3h6v6" />
                <path d="m10 14 11-11" />
              </svg>
              Launch App
            </button>
            <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[180px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
              {app.launch_mode === "external" ? "Open in a new tab" : "Open in the platform"}
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {app.launch_mode === "embedded" && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Container</h2>
            <div className="flex items-center gap-1">
              <div className="group relative inline-flex">
                <button
                  onClick={handleDeploy}
                  disabled={busy}
                  aria-label="Redeploy"
                  className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.69-3L3 21" />
                    <path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.69 3L21 3" />
                    <path d="M21 16v5h-5" />
                    <path d="M3 8V3h5" />
                  </svg>
                </button>
                <span className="pointer-events-none absolute top-full right-0 mt-1 w-max rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                  Redeploy
                </span>
              </div>
              <div className="group relative inline-flex">
                <button
                  onClick={handleStop}
                  disabled={busy || app.runtime_status === "stopped"}
                  aria-label="Stop container"
                  className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <rect x="6" y="6" width="12" height="12" rx="1.5" />
                  </svg>
                </button>
                <span className="pointer-events-none absolute top-full right-0 mt-1 w-max rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                  Stop container
                </span>
              </div>
            </div>
          </div>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-gray-500">Image</dt>
              <dd className="font-mono text-gray-900">
                {app.docker_image}:{app.docker_tag || "latest"}
              </dd>
            </div>
            <div>
              <dt className="text-gray-500">Container port</dt>
              <dd className="font-mono text-gray-900">{app.container_port}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Endpoint</dt>
              <dd className="font-mono text-gray-900">{app.runtime_endpoint || "—"}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Last deployed</dt>
              <dd className="text-gray-900">
                {app.last_deployed_at ? new Date(app.last_deployed_at).toLocaleString() : "—"}
              </dd>
            </div>
          </dl>
          {app.last_build_error && (
            <pre className="mt-3 overflow-x-auto rounded bg-red-50 p-2 text-xs text-red-700">
              {app.last_build_error}
            </pre>
          )}
        </section>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="text-lg font-semibold text-gray-900">Recent launches</h2>
        {launches.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No launches yet.</p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="py-1">When</th>
                <th>User</th>
                <th>Mode</th>
                <th>IP</th>
              </tr>
            </thead>
            <tbody>
              {launches.map((l) => (
                <tr key={l.id} className="border-t border-gray-100">
                  <td className="py-1.5 text-gray-700">{new Date(l.created_at).toLocaleString()}</td>
                  <td className="text-gray-700">{l.launcher_name || l.launched_by}</td>
                  <td className="text-gray-700">{l.launch_mode}</td>
                  <td className="text-gray-500">{l.client_ip || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

    </div>
  );
}
