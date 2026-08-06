"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  type AuditLog,
  type Org,
  type PaginatedResponse,
  type Role,
  type User,
} from "@/lib/api";

interface AuditLogsPanelProps {
  /** API endpoint for fetching audit logs. */
  logsApiPath: string;
  /** API endpoint for listing users (name resolution). */
  usersApiPath?: string;
  /** API endpoint for listing orgs (name resolution). */
  orgsApiPath?: string;
  /** API endpoint for listing roles (name resolution). */
  rolesApiPath?: string;
}

export default function AuditLogsPanel({
  logsApiPath,
  usersApiPath,
  orgsApiPath,
  rolesApiPath,
}: AuditLogsPanelProps) {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [actionFilter, setActionFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Available filter options (discovered from data)
  const [availableActions, setAvailableActions] = useState<string[]>([]);
  const [availableResourceTypes, setAvailableResourceTypes] = useState<
    string[]
  >([]);

  // Lookup maps for resolving IDs to names
  const [userMap, setUserMap] = useState<Record<string, string>>({});
  const [orgMap, setOrgMap] = useState<Record<string, string>>({});
  const [roleMap, setRoleMap] = useState<Record<string, string>>({});
  const [mapsReady, setMapsReady] = useState(false);

  // Detail modal
  const [detailLog, setDetailLog] = useState<AuditLog | null>(null);

  const limit = 30;

  // Load reference data for name resolution
  useEffect(() => {
    let cancelled = false;

    async function loadMaps() {
      const promises: Promise<void>[] = [];

      if (usersApiPath) {
        promises.push(
          apiGet<PaginatedResponse<User>>(usersApiPath, { limit: "200" })
            .then((data) => {
              if (cancelled) return;
              const map: Record<string, string> = {};
              for (const u of data.items) {
                map[u.id] = u.email;
              }
              setUserMap(map);
            })
            .catch(() => {}),
        );
      }

      if (orgsApiPath) {
        promises.push(
          apiGet<PaginatedResponse<Org>>(orgsApiPath, { limit: "200" })
            .then((data) => {
              if (cancelled) return;
              const map: Record<string, string> = {};
              for (const o of data.items) {
                map[o.id] = o.slug;
              }
              setOrgMap(map);
            })
            .catch(() => {}),
        );
      }

      if (rolesApiPath) {
        promises.push(
          apiGet<Role[]>(rolesApiPath)
            .then((roles) => {
              if (cancelled) return;
              const map: Record<string, string> = {};
              for (const r of roles) {
                map[r.id] = r.name;
              }
              setRoleMap(map);
            })
            .catch(() => {}),
        );
      }

      await Promise.allSettled(promises);
      if (!cancelled) setMapsReady(true);
    }

    loadMaps();
    return () => {
      cancelled = true;
    };
  }, [usersApiPath, orgsApiPath, rolesApiPath]);

  const fetchLogs = useCallback(async () => {
    if (!mapsReady) return;
    setLoading(true);
    setError("");
    try {
      const params: Record<string, string> = {
        skip: String(page * limit),
        limit: String(limit),
      };
      if (actionFilter) params.action = actionFilter;
      if (resourceTypeFilter) params.resource_type = resourceTypeFilter;

      const data = await apiGet<PaginatedResponse<AuditLog>>(
        logsApiPath,
        params,
      );
      setLogs(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      const msg =
        e instanceof Error ? e.message : "Failed to load audit logs";
      setError(msg);
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [mapsReady, logsApiPath, page, actionFilter, resourceTypeFilter]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // Discover available filter values once maps are ready
  useEffect(() => {
    if (!mapsReady) return;
    apiGet<PaginatedResponse<AuditLog>>(logsApiPath, {
      skip: "0",
      limit: "200",
    })
      .then((data) => {
        const actions = new Set<string>();
        const resourceTypes = new Set<string>();
        for (const l of data.items) {
          actions.add(l.action);
          resourceTypes.add(l.resource_type);
        }
        setAvailableActions(Array.from(actions).sort());
        setAvailableResourceTypes(Array.from(resourceTypes).sort());
      })
      .catch(() => {});
  }, [mapsReady, logsApiPath]);

  const totalPages = Math.ceil(total / limit);

  /** Resolve a resource ID to a human-readable name based on resource_type */
  const resolveResource = (log: AuditLog) => {
    const { resource_type, resource_id, details } = log;
    if (!resource_id) return "-";

    if (resource_type === "user" || resource_type === "auth") {
      if (userMap[resource_id]) return userMap[resource_id];
      if (details?.email) return String(details.email);
    }
    if (resource_type === "org") {
      if (orgMap[resource_id]) return orgMap[resource_id];
      if (details?.slug) return String(details.slug);
    }
    if (resource_type === "role") {
      if (roleMap[resource_id]) return roleMap[resource_id];
      if (details?.name) return String(details.name);
    }
    // For llm_provider and other types, try details.slug then details.name
    if (details?.slug) return String(details.slug);
    if (details?.name) return String(details.name);

    return resource_id.slice(0, 8) + "...";
  };

  /** Resolve a user ID to name */
  const resolveUser = (log: AuditLog) => {
    const { user_id, details } = log;
    if (!user_id) return "-";
    if (userMap[user_id]) return userMap[user_id];
    if (details?.email) return String(details.email);
    return user_id.slice(0, 8) + "...";
  };

  return (
    <div>
      {/* Filters */}
      <div className="mb-4 flex items-center gap-3">
        <select
          value={actionFilter}
          onChange={(e) => {
            setActionFilter(e.target.value);
            setPage(0);
          }}
          className="w-52 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="">All actions</option>
          {availableActions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={resourceTypeFilter}
          onChange={(e) => {
            setResourceTypeFilter(e.target.value);
            setPage(0);
          }}
          className="w-52 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="">All resource types</option>
          {availableResourceTypes.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <span className="text-sm text-gray-500">{total} entries</span>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Resource Type</th>
              <th className="px-4 py-3">Target</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">IP Address</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {loading ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-8 text-center text-gray-400"
                >
                  Loading...
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-8 text-center text-gray-400"
                >
                  No audit log entries found
                </td>
              </tr>
            ) : (
              logs.map((log) => (
                <tr key={log.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-xs text-gray-600 whitespace-nowrap">
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                      {log.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {log.resource_type}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {resolveResource(log)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {resolveUser(log)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {log.ip_address ?? "-"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setDetailLog(log)}
                      className="group relative inline-flex items-center justify-center rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                      aria-label="View details"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                      <span className="pointer-events-none absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-800 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                        Show detail
                      </span>
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex items-center gap-2">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-gray-600">
            Page {page + 1} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}

      {/* Detail modal */}
      {detailLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                Audit Log Detail
              </h3>
              <button
                onClick={() => setDetailLog(null)}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                <svg
                  className="h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2}
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            <dl className="space-y-3 text-sm">
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  Action
                </dt>
                <dd>
                  <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                    {detailLog.action}
                  </span>
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  Timestamp
                </dt>
                <dd className="text-gray-900">
                  {new Date(detailLog.timestamp).toLocaleString()}
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  Actor
                </dt>
                <dd className="text-gray-900">
                  {resolveUser(detailLog)}
                  {detailLog.user_id && (
                    <span className="ml-2 font-mono text-xs text-gray-400">
                      {detailLog.user_id}
                    </span>
                  )}
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  Resource Type
                </dt>
                <dd className="text-gray-900">{detailLog.resource_type}</dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  Resource
                </dt>
                <dd className="text-gray-900">
                  {resolveResource(detailLog)}
                  {detailLog.resource_id && (
                    <span className="ml-2 font-mono text-xs text-gray-400">
                      {detailLog.resource_id}
                    </span>
                  )}
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  IP Address
                </dt>
                <dd className="text-gray-900">
                  {detailLog.ip_address ?? "-"}
                </dd>
              </div>
              <div className="flex gap-3">
                <dt className="w-28 shrink-0 font-medium text-gray-500">
                  User Agent
                </dt>
                <dd className="max-w-sm truncate text-gray-600 text-xs">
                  {detailLog.user_agent ?? "-"}
                </dd>
              </div>
              <div>
                <dt className="mb-1 font-medium text-gray-500">Details</dt>
                <dd>
                  {Object.keys(detailLog.details).length > 0 ? (
                    <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-3 text-xs text-gray-800">
                      {JSON.stringify(detailLog.details, null, 2)}
                    </pre>
                  ) : (
                    <span className="text-gray-400">
                      No additional details
                    </span>
                  )}
                </dd>
              </div>
            </dl>

            <div className="mt-5 flex justify-end">
              <button
                onClick={() => setDetailLog(null)}
                className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
