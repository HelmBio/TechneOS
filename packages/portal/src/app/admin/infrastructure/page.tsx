"use client";

import { useCallback, useEffect, useState } from "react";
import {
  apiGet,
  type DockerContainer,
  type DockerContainerLogs,
} from "@/lib/api";

export default function AdminInfrastructurePage() {
  const [containers, setContainers] = useState<DockerContainer[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Log viewer state
  const [logsData, setLogsData] = useState<DockerContainerLogs | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsTail, setLogsTail] = useState(200);

  const fetchContainers = useCallback(async () => {
    try {
      const data = await apiGet<DockerContainer[]>(
        "/api/v1/admin/docker/containers",
      );
      setContainers(data);
      setLastRefresh(new Date());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchContainers();
    const interval = setInterval(fetchContainers, 15000);
    // Re-fetch immediately when the session token is refreshed
    const onRefreshed = () => fetchContainers();
    window.addEventListener("token-refreshed", onRefreshed);
    return () => {
      clearInterval(interval);
      window.removeEventListener("token-refreshed", onRefreshed);
    };
  }, [fetchContainers]);

  const viewLogs = async (containerId: string) => {
    setLogsLoading(true);
    setLogsData(null);
    try {
      const data = await apiGet<DockerContainerLogs>(
        `/api/v1/admin/docker/containers/${containerId}/logs`,
        { tail: String(logsTail) },
      );
      setLogsData(data);
    } catch (e) {
      console.error(e);
      setLogsData({
        container_id: containerId,
        container_name: containerId,
        logs: "Failed to fetch logs",
      });
    } finally {
      setLogsLoading(false);
    }
  };

  const refreshLogs = () => {
    if (logsData) {
      viewLogs(logsData.container_id);
    }
  };

  const statusColor = (status: string, health: string | null) => {
    if (status === "running") {
      if (health === "healthy") return "bg-green-500";
      if (health === "unhealthy") return "bg-red-500";
      if (health === "starting") return "bg-yellow-500";
      return "bg-green-500";
    }
    if (status === "exited") return "bg-gray-400";
    if (status === "paused") return "bg-yellow-500";
    return "bg-gray-400";
  };

  const statusBadge = (status: string, health: string | null) => {
    const label = health ? `${status} (${health})` : status;
    if (status === "running") {
      if (health === "unhealthy")
        return "bg-red-100 text-red-800";
      return "bg-green-100 text-green-800";
    }
    if (status === "exited") return "bg-gray-100 text-gray-800";
    return "bg-yellow-100 text-yellow-800";
  };

  if (loading) {
    return <p className="text-gray-500">Loading Docker containers...</p>;
  }

  const runningCount = containers.filter((c) => c.state === "running").length;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {runningCount}/{containers.length} containers running
          {lastRefresh && (
            <> &middot; Last checked {lastRefresh.toLocaleTimeString()}</>
          )}
        </p>
        <button
          onClick={fetchContainers}
          className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {/* Container table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3">Container</th>
              <th className="px-4 py-3">Image</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Ports</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {containers.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-gray-400"
                >
                  No Docker containers found. Is Docker running?
                </td>
              </tr>
            ) : (
              containers.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block h-2.5 w-2.5 rounded-full ${statusColor(c.state, c.health)}`}
                      />
                      <div>
                        <p className="font-medium text-gray-900">{c.name}</p>
                        <p className="font-mono text-xs text-gray-400">
                          {c.id}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">
                    {c.image}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(c.state, c.health)}`}
                    >
                      {c.health ? `${c.state} (${c.health})` : c.state}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-0.5">
                      {c.ports.length > 0 ? (
                        c.ports.map((p, i) => (
                          <span
                            key={i}
                            className="font-mono text-xs text-gray-500"
                          >
                            {p}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-gray-400">-</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                    {c.created
                      ? new Date(c.created).toLocaleString()
                      : "-"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => viewLogs(c.name)}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800"
                    >
                      Logs
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-gray-400">
        Auto-refreshes every 15 seconds
      </p>

      {/* Log viewer modal */}
      {(logsData || logsLoading) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="flex h-[80vh] w-full max-w-4xl flex-col rounded-lg bg-white shadow-xl">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">
                  Container Logs
                </h3>
                {logsData && (
                  <p className="text-sm text-gray-500">
                    {logsData.container_name}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-gray-500">Tail:</label>
                <select
                  value={logsTail}
                  onChange={(e) => setLogsTail(Number(e.target.value))}
                  className="rounded border border-gray-300 px-2 py-1 text-xs"
                >
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                  <option value={500}>500</option>
                  <option value={1000}>1000</option>
                  <option value={2000}>2000</option>
                </select>
                <button
                  onClick={refreshLogs}
                  disabled={logsLoading}
                  className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                >
                  Refresh
                </button>
                <button
                  onClick={() => {
                    setLogsData(null);
                  }}
                  className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50"
                >
                  Close
                </button>
              </div>
            </div>

            {/* Log content */}
            <div className="flex-1 overflow-auto bg-gray-900 p-4">
              {logsLoading ? (
                <p className="text-sm text-gray-400">Loading logs...</p>
              ) : logsData ? (
                <pre className="whitespace-pre-wrap font-mono text-xs leading-5 text-gray-200">
                  {logsData.logs || "(empty)"}
                </pre>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
