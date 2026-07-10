"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { useParams, useRouter } from "next/navigation";

import {
  apiGet,
  apiPost,
  type ToolRun,
  type ToolRunDetail,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { isActive, isTerminal, formatDuration, downloadFile } from "@/lib/run-utils";
import { StatusBadge } from "@/components/run/status-badge";
import { RunActionButtons } from "@/components/run/run-action-buttons";
import { RestartLineage } from "@/components/run/restart-lineage";
import { RunFileTable, type RunFile } from "@/components/run/run-file-table";

export default function ToolRunDetailPage() {
  const execLabel = useLabel("exec.tool.plural");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [run, setRun] = useState<ToolRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [logs, setLogs] = useState<string>("");
  const [logsLoading, setLogsLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRun = useCallback(() => {
    if (!id) return;
    apiGet<ToolRunDetail>(`/api/v1/tool-runs/${id}`)
      .then(setRun)
      .catch(() => setRun(null))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (authLoading || !user) return;
    setLoading(true);
    fetchRun();
  }, [user, authLoading, fetchRun]);

  useEffect(() => {
    if (!run || isTerminal(run.status)) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(fetchRun, 4000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [run, fetchRun]);

  const fetchLogs = useCallback(async () => {
    if (!run) return;
    setLogsLoading(true);
    try {
      const data = await apiGet<{ logs: string }>(`/api/v1/tool-runs/${run.id}/logs`);
      setLogs(data.logs || "");
    } catch {
      setLogs("(no logs yet)");
    } finally {
      setLogsLoading(false);
    }
  }, [run]);

  // Auto-fetch persisted logs for terminal runs
  useEffect(() => {
    if (run && isTerminal(run.status) && run.log_storage_key) {
      fetchLogs();
    }
  }, [run, fetchLogs]);

  async function handleCancel() {
    if (!run) return;
    setCancelling(true);
    try {
      await apiPost(`/api/v1/tool-runs/${run.id}/cancel`);
      fetchRun();
    } finally {
      setCancelling(false);
    }
  }

  async function handleRestart() {
    if (!run) return;
    setRestarting(true);
    try {
      const data = await apiPost<ToolRun>(`/api/v1/tool-runs/${run.id}/restart`);
      router.push(`/tool-runs/${data.id}`);
    } finally {
      setRestarting(false);
    }
  }

  async function handleDownload(file: RunFile) {
    if (!run) return;
    const data = await apiGet<{ download_url: string }>(
      `/api/v1/tool-runs/${run.id}/artifacts/${file.id}/download`,
    );
    await downloadFile(data.download_url, file.file_name);
  }

  if (authLoading || loading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>
        .
      </p>
    );
  if (!run) return <p className="p-8 text-red-500">Run not found.</p>;

  const runActive = isActive(run.status);
  const canCancel = runActive;
  const canRestart = (run.status === "failed" || run.status === "cancelled") && !run.restarted_from;

  const artifactFiles: RunFile[] = (run.artifacts || []).map((a) => ({
    id: a.id,
    file_name: a.file_name,
    file_size: a.file_size,
    file_type: a.io_type as "input" | "output",
  }));

  const artifactsEmptyMsg = isTerminal(run.status)
    ? "No artifacts were produced."
    : "Artifacts will appear here once the tool completes.";

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/tool-runs" className="hover:text-blue-600">
          {execLabel}
        </Link>
        <span>/</span>
        {run.tool_name && run.tool_id ? (
          <Link href={`/tools/${run.tool_slug || run.tool_id}`} className="hover:text-blue-600">
            {run.tool_name}
          </Link>
        ) : (
          <span className="font-mono">{run.tool_version_id.slice(0, 8)}…</span>
        )}
        <span>/</span>
        <span className="font-mono">v{run.tool_version_num || "?"}</span>
        <span>/</span>
        <span className="font-mono">{run.id.split("-")[0]}…</span>
        <StatusBadge status={run.status} />
      </div>

      {/* Summary */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-gray-900">Summary</h2>
          <RunActionButtons
            canCancel={canCancel}
            canRestart={canRestart}
            cancelling={cancelling}
            restarting={restarting}
            onCancel={handleCancel}
            onRestart={handleRestart}
          />
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
            <div className="flex items-center gap-1">
              <span className="text-gray-400">Submitted By:</span>
              <span className="text-gray-700">{run.submitted_by_email || run.submitted_by.slice(0, 12) + "…"}</span>
            </div>
            {run.started_at && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Started On:</span>
                <span className="text-gray-700">{new Date(run.started_at).toLocaleString()}</span>
              </div>
            )}
            {run.finished_at && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Completed On:</span>
                <span className="text-gray-700">{new Date(run.finished_at).toLocaleString()}</span>
              </div>
            )}
            <div className="flex items-center gap-1">
              <span className="text-gray-400">Duration:</span>
              <span className="text-gray-700">{formatDuration(run.started_at, run.finished_at, run.status)}</span>
            </div>
          </div>
        </div>
      </section>

      {run.restarted_from ? (
        <RestartLineage
          restartedFrom={run.restarted_from}
          runType="tool"
          parameters={run.parameters}
        />
      ) : Object.keys(run.parameters).length > 0 ? (
        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Parameters</h2>
          <pre className="overflow-auto max-h-72 rounded bg-gray-50 border border-gray-200 p-3 text-xs">
            {JSON.stringify(run.parameters, null, 2)}
          </pre>
        </section>
      ) : null}

      {run.error_message && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <strong className="font-semibold">Error:</strong> {run.error_message}
        </div>
      )}

      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Artifacts</h2>
        <RunFileTable
          files={artifactFiles}
          onDownload={handleDownload}
          showType={true}
          emptyMessage={artifactsEmptyMsg}
        />
      </section>

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-gray-900">Logs</h2>
          <button
            onClick={fetchLogs}
            disabled={logsLoading}
            className="text-sm text-blue-600 hover:underline disabled:opacity-50"
          >
            {logsLoading ? "Loading..." : logs ? "Refresh" : "Fetch logs"}
          </button>
        </div>
        {logs && (
          <pre className="overflow-auto max-h-96 rounded bg-gray-900 text-gray-100 p-3 text-xs font-mono">
            {logs}
          </pre>
        )}
      </section>
    </div>
  );
}
