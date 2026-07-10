"use client";

import { useEffect, useMemo, useState } from "react";

import { apiGet, type HumanTaskRun, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLabel } from "@/lib/labels";
import TaskRunTable from "@/components/tool/task-run-table";
import { RUN_STATUS_COLORS } from "@/lib/run-utils";

const PAGE_SIZE_OPTIONS = [10, 15, 25, 50];

export default function TaskRunsPage() {
  const { user, loading: authLoading } = useAuth();
  const execLabel = useLabel("exec.task.plural");
  const [taskRuns, setTaskRuns] = useState<HumanTaskRun[]>([]);
  const [total, setTotal] = useState(0);
  const [totalAll, setTotalAll] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const statusFilterKey = useMemo(() => [...statusFilter].sort().join(","), [statusFilter]);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Fetch unfiltered total once on mount.
  useEffect(() => {
    if (authLoading || !user) return;
    apiGet<PaginatedResponse<HumanTaskRun>>("/api/v1/task-runs", { skip: "0", limit: "0" })
      .then((data) => setTotalAll(data.total))
      .catch(() => {});
  }, [user, authLoading]);

  useEffect(() => {
    if (authLoading || !user) return;
    const skip = (page - 1) * pageSize;
    const params: Record<string, string> = { skip: String(skip), limit: String(pageSize) };
    if (statusFilter.size > 0) params.status = [...statusFilter].join(",");
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<HumanTaskRun>>("/api/v1/task-runs", params);
        setTaskRuns(data.items);
        setTotal(data.total);
      } catch {
        setTaskRuns([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, statusFilterKey, page, pageSize]);

  // Reset to page 1 when filter or page size changes (adjust state during
  // render rather than in an effect — avoids an extra post-mount render).
  const resetKey = `${statusFilterKey}|${pageSize}`;
  const [prevResetKey, setPrevResetKey] = useState(resetKey);
  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey);
    setPage(1);
  }

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to view task runs.</p>;

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">
          {execLabel}
        <span className="ml-2 rounded-full bg-gray-100 px-2.5 py-0.5 text-sm font-semibold tabular-nums text-gray-600">
          {statusFilter.size > 0 ? `${total || 0} out of ${totalAll || 0}` : `${totalAll || 0}`}
        </span>
        </h1>
        <div className="flex items-center gap-2">
          {["pending", "accepted", "in_progress", "completed", "declined", "cancelled", "escalated"].map((s) => {
            // Match the STATUS column badge colours; dim when inactive, ring when active.
            const display = s.replace("_", " ");
            const color = RUN_STATUS_COLORS[display] || "bg-gray-100 text-gray-800";
            const active = statusFilter.has(s);
            return (
              <button
                key={s} onClick={() => setStatusFilter((prev) => {
                  const next = new Set(prev);
                  if (next.has(s)) next.delete(s);
                  else next.add(s);
                  return next;
                })}
                className={`rounded-full px-3 py-1 text-sm font-medium capitalize transition-all ${color} ${
                  active ? "ring-2 ring-offset-1 ring-blue-500" : "opacity-60 hover:opacity-100"
                }`}
              >{display}</button>
            );
          })}
        </div>
      </div>

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : taskRuns.length === 0 ? (
        <p className="mt-6 text-gray-500">No task runs found.</p>
      ) : (
        <>
          <div className="mt-6">
            <TaskRunTable taskRuns={taskRuns} showTaskColumn={true} />
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * pageSize + 1}&ndash;{Math.min(page * pageSize, total)} of {total}
              </p>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-1.5">
                  <label htmlFor="page-size" className="text-sm text-gray-500">Rows</label>
                  <select id="page-size" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  >
                    {PAGE_SIZE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >Previous</button>
                  <span className="px-2 text-sm text-gray-600">{page} / {totalPages}</span>
                  <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >Next</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
