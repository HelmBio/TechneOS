"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, type ServiceHealth, type ServiceLogs } from "@/lib/api";

export default function AdminServicesPage() {
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Log viewer state
  const [logsData, setLogsData] = useState<ServiceLogs | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsTail, setLogsTail] = useState(200);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await apiGet<ServiceHealth[]>(
        "/api/v1/admin/services/health",
      );
      setServices(data);
      setLastRefresh(new Date());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    const onRefreshed = () => fetchHealth();
    window.addEventListener("token-refreshed", onRefreshed);
    return () => {
      clearInterval(interval);
      window.removeEventListener("token-refreshed", onRefreshed);
    };
  }, [fetchHealth]);

  const viewLogs = async (serviceName: string) => {
    setLogsLoading(true);
    setLogsData(null);
    try {
      const data = await apiGet<ServiceLogs>(
        `/api/v1/admin/services/${serviceName}/logs`,
        { tail: String(logsTail) },
      );
      setLogsData(data);
    } catch (e) {
      console.error(e);
      setLogsData({
        service_name: serviceName,
        logs: "Failed to fetch logs",
      });
    } finally {
      setLogsLoading(false);
    }
  };

  const refreshLogs = () => {
    if (logsData) {
      viewLogs(logsData.service_name);
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case "healthy":
        return "bg-green-100 text-green-800";
      case "unhealthy":
        return "bg-yellow-100 text-yellow-800";
      default:
        return "bg-red-100 text-red-800";
    }
  };

  const dotColor = (status: string) => {
    switch (status) {
      case "healthy":
        return "bg-green-500";
      case "unhealthy":
        return "bg-yellow-500";
      default:
        return "bg-red-500";
    }
  };

  if (loading) {
    return <p className="text-gray-500">Checking service health...</p>;
  }

  const healthyCount = services.filter((s) => s.status === "healthy").length;
  const sorted = [...services].sort((a, b) => a.url.localeCompare(b.url));

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {healthyCount}/{services.length} services healthy
          {lastRefresh && (
            <> &middot; Last checked {lastRefresh.toLocaleTimeString()}</>
          )}
        </p>
        <button
          onClick={fetchHealth}
          className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-600 hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs font-medium uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3">Service</th>
              <th className="px-4 py-3">URL</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Latency</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {sorted.map((svc) => (
              <tr key={svc.name} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium capitalize text-gray-900">
                  <span
                    className={`mr-2 inline-block h-2.5 w-2.5 rounded-full ${dotColor(svc.status)}`}
                  />
                  {svc.name}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-gray-500">
                  {svc.url}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(svc.status)}`}
                  >
                    {svc.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600">
                  {svc.latency_ms != null ? `${svc.latency_ms} ms` : "-"}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => viewLogs(svc.name)}
                    className="text-xs font-medium text-blue-600 hover:text-blue-800"
                  >
                    Logs
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-gray-400">
        Auto-refreshes every 30 seconds
      </p>

      {/* Log viewer modal */}
      {(logsData || logsLoading) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="flex h-[80vh] w-full max-w-4xl flex-col rounded-lg bg-white shadow-xl">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">
                  Service Logs
                </h3>
                {logsData && (
                  <p className="text-sm text-gray-500">
                    {logsData.service_name}
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
