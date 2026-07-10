"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import {
  apiGet,
  apiPost,
  type Artifact,
  type PipelineWithVersions,
  type PipelineRunDetail,
  type PipelineStepConfig,
  type StepRun,
  type ArtifactDownload,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { RUN_STATUS_COLORS, RUN_STATUS_ICONS, isActive as isActiveStatus, isTerminal as isTerminalStatus, formatDuration } from "@/lib/run-utils";
import { StatusBadge } from "@/components/run/status-badge";
import { RunActionButtons } from "@/components/run/run-action-buttons";
import { RestartLineage } from "@/components/run/restart-lineage";
import PipelineGraph from "@/components/pipeline-graph";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function RunDetailPage() {
  const execLabel = useLabel("exec.pipeline.plural");
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading } = useAuth();
  const [run, setRun] = useState<PipelineRunDetail | null>(null);
  const [pipeline, setPipeline] = useState<PipelineWithVersions | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const router = useRouter();

  const fetchRun = useCallback(() => {
    if (!id) return;
    setLoading(true);
    apiGet<PipelineRunDetail>(`/api/v1/pipeline-runs/${id}`)
      .then(setRun)
      .catch(() => setRun(null))
      .finally(() => setLoading(false));
  }, [id]);

  // Initial fetch
  useEffect(() => {
    if (authLoading || !user) return;
    fetchRun();
  }, [user, authLoading, fetchRun]);

  // Fetch pipeline definition for graph visualization
  useEffect(() => {
    if (!run?.pipeline_id) return;
    apiGet<PipelineWithVersions>(`/api/v1/pipelines/${run.pipeline_id}`)
      .then(setPipeline)
      .catch(() => setPipeline(null));
  }, [run?.pipeline_id]);

  // SSE connection for live updates
  useEffect(() => {
    if (!run || !id || isTerminalStatus(run.status)) return;

    const controller = new AbortController();
    abortRef.current = controller;

    const token = typeof window !== "undefined" ? localStorage.getItem("techneos_access_token") : null;
    const url = `${API_BASE}/api/v1/pipeline-runs/${id}/events`;

    // Polling fallback in case SSE fails to connect
    const pollInterval = setInterval(() => {
      if (!isTerminalStatus(run.status)) {
        apiGet<PipelineRunDetail>(`/api/v1/pipeline-runs/${id}`)
          .then(setRun)
          .catch(() => {});
      }
    }, 5000);

    async function connectSSE() {
      try {
        const resp = await fetch(url, {
          headers: {
            Accept: "text/event-stream",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) return;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Parse SSE frames
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          let eventType = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                handleSSEEvent(eventType || data.type, data);
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
      }
    }

    connectSSE();
    return () => {
      controller.abort();
      abortRef.current = null;
      clearInterval(pollInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, run?.status]);

  function handleSSEEvent(eventType: string, data: Record<string, unknown>) {
    if (eventType === "run_status") {
      setRun((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          status: data.status as string,
          started_at: (data.started_at as string) ?? prev.started_at,
          finished_at: (data.finished_at as string) ?? prev.finished_at,
          error_message: (data.error_message as string) ?? prev.error_message,
        };
      });
    } else if (eventType === "step_status") {
      setRun((prev) => {
        if (!prev) return prev;
        const stepName = data.step_name as string;
        const updatedSteps = prev.steps.map((s) =>
          s.step_name === stepName
            ? {
                ...s,
                status: data.status as string,
                started_at: (data.started_at as string) ?? s.started_at,
                finished_at: (data.finished_at as string) ?? s.finished_at,
                error_message: (data.error_message as string) ?? s.error_message,
              }
            : s,
        );
        return { ...prev, steps: updatedSteps };
      });
    } else if (eventType === "stream_end") {
      // Refresh full state from API
      fetchRun();
    }
  }

  const handleCancel = async () => {
    if (!id) return;
    setCancelling(true);
    try {
      await apiPost(`/api/v1/pipeline-runs/${id}/cancel`);
      fetchRun();
    } catch {
      // ignore
    } finally {
      setCancelling(false);
    }
  };

  const handleRestart = async () => {
    if (!id) return;
    setRestarting(true);
    try {
      const newRun = await apiPost<PipelineRunDetail>(`/api/v1/pipeline-runs/${id}/restart`);
      router.push(`/pipeline-runs/${newRun.id}`);
    } catch {
      // ignore
    } finally {
      setRestarting(false);
    }
  };

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please <a href="/login" className="text-blue-600 underline">log in</a> to view runs.
      </p>
    );
  if (loading) return <p className="p-8 text-gray-500">Loading run...</p>;
  if (!run) return <p className="p-8 text-red-500">Run not found.</p>;

  const runActive = isActiveStatus(run.status);
  const canCancel = runActive;
  const canRestart = (run.status === "failed" || run.status === "cancelled") && !run.restarted_from;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/pipeline-runs" className="hover:text-blue-600">{execLabel}</Link>
        <span>/</span>
        {run.pipeline_name ? (
          <Link href={`/pipelines/${run.pipeline_slug || run.pipeline_id}`} className="hover:text-blue-600">
            {run.pipeline_name}
          </Link>
        ) : (
          <span className="font-mono">{run.pipeline_id?.slice(0, 8)}…</span>
        )}
        <span>/</span>
        <span className="font-mono">v{run.pipeline_version ?? "?"}</span>
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
              <span className="text-gray-700">{run.submitted_by_email || run.submitted_by.slice(0, 12) + "\u2026"}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-gray-400">Submitted:</span>
              <span className="text-gray-700">{new Date(run.created_at).toLocaleString()}</span>
            </div>
            {run.started_at && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Started:</span>
                <span className="text-gray-700">{new Date(run.started_at).toLocaleString()}</span>
              </div>
            )}
            {run.finished_at && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Completed:</span>
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

      {/* Restart lineage */}
      {run.restarted_from ? (
        <RestartLineage
          restartedFrom={run.restarted_from}
          runType="pipeline"
          parameters={run.parameters}
        />
      ) : Object.keys(run.parameters).length > 0 ? (
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Parameters</h2>
          <pre className="max-h-60 overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-4 text-xs">
            {JSON.stringify(run.parameters, null, 2)}
          </pre>
        </div>
      ) : null}

      {/* Error message */}
      {run.error_message && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <h3 className="text-sm font-semibold text-red-900 mb-1">Error</h3>
          <p className="text-sm text-red-800 whitespace-pre-wrap">{run.error_message}</p>
        </div>
      )}

      {/* Pipeline graph with live step statuses */}
      {pipeline && (
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            Pipeline Graph
          </h2>
          <PipelineGraph
            steps={(() => {
              const pv = pipeline.versions?.find((v) => v.id === run.version_id);
              return (pv?.steps ?? []) as unknown as PipelineStepConfig[];
            })()}
            stepStatuses={run.steps.map((s) => ({
              step_name: s.step_name,
              status: s.status,
            }))}
            height="300px"
          />
        </div>
      )}

      {/* Steps progress */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">
          Steps ({run.steps.length})
        </h2>
        {run.steps.length === 0 ? (
          <p className="text-sm text-gray-500">No step data available yet.</p>
        ) : (
          <div className="space-y-2">
            {run.steps.map((step) => (
              <StepCard key={step.id} step={step} runId={run.id} />
            ))}
          </div>
          )}
        </div>

      {/* Artifacts */}
      {run.artifacts.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-lg font-semibold text-gray-900">
              Artifacts ({run.artifacts.length})
            </h2>
            <DownloadAllButton runId={run.id} artifacts={run.artifacts} />
          </div>
          <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
            <ArtifactTree runId={run.id} artifacts={run.artifacts} steps={run.steps} />
          </div>
        </div>
      )}
    </div>
  );
}

function ArtifactTree({ runId, artifacts, steps }: { runId: string; artifacts: Artifact[]; steps: StepRun[] }) {
  // Group artifacts by step_name (null → "other")
  const grouped = new Map<string, Artifact[]>();
  for (const a of artifacts) {
    const key = a.step_name || "other";
    const list = grouped.get(key);
    if (list) list.push(a);
    else grouped.set(key, [a]);
  }

  // Order folders by step order, with "other" at the end
  const stepOrder = new Map(steps.map((s, i) => [s.step_name, i]));
  const sortedKeys = [...grouped.keys()].sort((a, b) => {
    const ai = stepOrder.get(a) ?? Infinity;
    const bi = stepOrder.get(b) ?? Infinity;
    return ai - bi;
  });

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(grouped.keys()));

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const formatSize = (bytes: number) =>
    bytes > 1024 * 1024
      ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
      : `${(bytes / 1024).toFixed(1)} KB`;

  return (
    <div className="py-2 font-mono text-sm">
      {sortedKeys.map((step) => {
        const files = grouped.get(step)!;
        return (
        <div key={step}>
          {/* Folder row */}
          <button
            onClick={() => toggle(step)}
            className="flex w-full items-center gap-1.5 px-4 py-1.5 text-left hover:bg-gray-50"
          >
            <span className="text-gray-400 w-4 text-center">
              {expanded.has(step) ? "▾" : "▸"}
            </span>
            <span className="text-yellow-600">
              {expanded.has(step) ? "📂" : "📁"}
            </span>
            <span className="font-medium text-gray-800">{step}</span>
            <span className="ml-auto text-xs text-gray-400">{files.length} file{files.length !== 1 ? "s" : ""}</span>
          </button>
          {/* File rows */}
          {expanded.has(step) &&
            files.map((a) => (
              <div
                key={a.id}
                className="flex items-center gap-1.5 py-1.5 pl-12 pr-4 hover:bg-gray-50"
              >
                <span className="text-gray-400">📄</span>
                <span className="text-gray-700 truncate" title={a.file_name}>
                  {a.file_name}
                </span>
                <span className="ml-1 text-xs text-gray-400">
                  {formatSize(a.file_size)}
                </span>
                <span className="ml-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                  {a.content_type.split("/").pop()}
                </span>
                <span className="ml-auto">
                  <DownloadButton
                    runId={runId}
                    artifactId={a.id}
                    downloadName={`${step}_${a.file_name}`}
                  />
                </span>
              </div>
            ))}
        </div>
        );
      })}
    </div>
  );
}

function DownloadAllButton({ runId, artifacts }: { runId: string; artifacts: Artifact[] }) {
  const [zipping, setZipping] = useState(false);

  const handleDownloadAll = async () => {
    setZipping(true);
    try {
      const JSZip = (await import("jszip")).default;
      const zip = new JSZip();

      for (const a of artifacts) {
        const folder = a.step_name || "other";
        const data = await apiGet<ArtifactDownload>(
          `/api/v1/pipeline-runs/${runId}/artifacts/${a.id}/download`,
        );
        const resp = await fetch(data.download_url);
        const blob = await resp.blob();
        zip.file(`${folder}/${a.file_name}`, blob);
      }

      const content = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(content);
      const link = document.createElement("a");
      link.href = url;
      link.download = `run-${runId.slice(0, 8)}-artifacts.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    } finally {
      setZipping(false);
    }
  };

  return (
    <button
      onClick={handleDownloadAll}
      disabled={zipping}
      className="group relative rounded-md border border-gray-300 p-1.5 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
    >
      {zipping ? (
        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" /></svg>
      ) : (
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="M12 11v6" /><path d="m9 14 3 3 3-3" /></svg>
      )}
      <span className="pointer-events-none absolute left-0 top-full mt-1 hidden w-max max-w-[250px] rounded bg-gray-800 px-2 py-1 text-xs text-white shadow group-hover:block">
        Download all files as a zip
      </span>
    </button>
  );
}

function DownloadButton({
  runId,
  artifactId,
  downloadName,
}: {
  runId: string;
  artifactId: string;
  downloadName?: string;
}) {
  const [loading, setLoading] = useState(false);

  const handleDownload = async () => {
    setLoading(true);
    try {
      const data = await apiGet<ArtifactDownload>(
        `/api/v1/pipeline-runs/${runId}/artifacts/${artifactId}/download`,
      );
      if (downloadName) {
        // Fetch as blob and trigger named download
        const resp = await fetch(data.download_url);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = downloadName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } else {
        window.open(data.download_url, "_blank");
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleDownload}
      disabled={loading}
      className="group relative rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-blue-600 disabled:opacity-50"
    >
      {loading ? (
        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" /></svg>
      ) : (
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
      )}
      <span className="pointer-events-none absolute right-0 top-full mt-1 hidden w-max max-w-[200px] rounded bg-gray-800 px-2 py-1 text-xs font-sans text-white shadow group-hover:block">
        Download this file
      </span>
    </button>
  );
}

function StepCard({ step, runId }: { step: StepRun; runId: string }) {
  const [showOutputs, setShowOutputs] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [logs, setLogs] = useState<string | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const hasOutputs = Object.keys(step.outputs).length > 0;
  const canShowLogs = step.status !== "pending";

  const fetchLogs = async () => {
    if (logs !== null) {
      setShowLogs(!showLogs);
      return;
    }
    setLogsLoading(true);
    setLogsError(null);
    try {
      const data = await apiGet<{ logs: string }>(
        `/api/v1/pipeline-runs/${runId}/steps/${step.step_name}/logs`,
      );
      setLogs(data.logs);
      setShowLogs(true);
    } catch (err: unknown) {
      setLogsError(err instanceof Error ? err.message : "Failed to fetch logs");
    } finally {
      setLogsLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full text-sm font-bold ${RUN_STATUS_COLORS[step.status] || "bg-gray-100 text-gray-800"}`}
          >
            {RUN_STATUS_ICONS[step.status] || "?"}
          </span>
          <span className="font-medium text-gray-900">{step.step_name}</span>
          <StatusBadge status={step.status} />
        </div>
        <div className="flex items-center gap-3">
          {canShowLogs && (
            <button
              onClick={fetchLogs}
              disabled={logsLoading}
              className="text-xs text-blue-600 hover:underline disabled:opacity-50"
            >
              {logsLoading ? "Loading..." : showLogs ? "Hide logs" : "View logs"}
            </button>
          )}
          <span className="text-xs text-gray-500">
            {formatDuration(step.started_at, step.finished_at, step.status)}
          </span>
        </div>
      </div>

      {step.error_message && (
        <p className="mt-2 text-sm text-red-600 whitespace-pre-wrap">{step.error_message}</p>
      )}

      {logsError && (
        <p className="mt-2 text-sm text-red-600">{logsError}</p>
      )}

      {showLogs && logs !== null && (
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-gray-900 p-3 text-xs text-green-300 font-mono">
          {logs}
        </pre>
      )}

      {hasOutputs && (
        <div className="mt-2">
          <button
            onClick={() => setShowOutputs(!showOutputs)}
            className="text-xs text-blue-600 hover:underline"
          >
            {showOutputs ? "Hide outputs" : "Show outputs"}
          </button>
          {showOutputs && (
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-gray-50 p-2 text-xs">
              {JSON.stringify(step.outputs, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
