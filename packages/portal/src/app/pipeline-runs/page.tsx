"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { apiGet, type PipelineRun, type PaginatedResponse } from "@/lib/api";
import { useLabel } from "@/lib/labels";
import { useAuth } from "@/lib/auth";
import { formatDuration, buildRunTree, buildPageNumbers } from "@/lib/run-utils";
import { StatusBadge } from "@/components/run/status-badge";

const PAGE_SIZE_OPTIONS = [10, 15, 25, 50];

function RunRow({ run, isChild }: { run: PipelineRun; isChild?: boolean }) {
  return (
    <tr className={isChild ? "bg-gray-50/60" : "hover:bg-gray-50"}>
      <td className="px-4 py-3">
        <div className={isChild ? "pl-6 flex items-center gap-1.5" : ""}>
          {isChild && (
            <svg className="h-3.5 w-3.5 shrink-0 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3v9h9" />
            </svg>
          )}
          <Link href={`/pipeline-runs/${run.id}`} className="font-mono text-sm text-blue-600 hover:underline">
            {run.name || `${run.id.slice(0, 12)}...`}
          </Link>
          {run.name && (
            <span className="ml-1.5 text-xs text-gray-400 font-mono">{run.id.slice(0, 8)}</span>
          )}
        </div>
        {/* If this is a child whose parent is NOT on the page, show a "from" hint */}
        {!isChild && run.restarted_from && (
          <div className="mt-0.5 flex items-center gap-1 text-xs text-gray-400">
            <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 4v6h6" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" /></svg>
            <span>from{" "}
              <Link href={`/pipeline-runs/${run.restarted_from}`} className="font-mono text-gray-500 hover:text-blue-600 hover:underline">
                {run.restarted_from.slice(0, 8)}...
              </Link>
            </span>
          </div>
        )}
      </td>
       <td className="px-4 py-3 text-sm text-gray-900">
        {run.pipeline_name && run.pipeline_id ? (
          <Link href={`/pipelines/${run.pipeline_slug || run.pipeline_id}`} className="text-blue-600 hover:underline">
            {run.pipeline_name}
          </Link>
        ) : (
          <span className="font-mono text-gray-500">{run.pipeline_id?.slice(0, 12) ?? run.version_id.slice(0, 12)}...</span>
        )}
      </td>
      <td className="px-4 py-3 text-sm text-gray-600">
        {run.pipeline_version != null ? `v${run.pipeline_version}` : "\u2014"}
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={run.status} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-600">
        {run.submitted_by_email || run.submitted_by.slice(0, 12) + "..."}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {new Date(run.created_at).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {formatDuration(run.started_at, run.finished_at, run.status)}
      </td>
    </tr>
  );
}

export default function RunsPage() {
  const execLabel = useLabel("exec.pipeline.plural");
  const { user, loading: authLoading } = useAuth();
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [total, setTotal] = useState(0);
  const [totalAll, setTotalAll] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const statusFilterKey = [...statusFilter].sort().join(",");

  function toggleStatus(value: string) {
    setStatusFilter((prev) => {
      const next = new Set(prev);
      if (next.has(value)) {
        next.delete(value);
      } else {
        next.add(value);
      }
      return next;
    });
  }
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  const [ancestors, setAncestors] = useState<Map<string, PipelineRun>>(new Map());

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const runTree = useMemo(() => buildRunTree(runs, ancestors), [runs, ancestors]);

  useEffect(() => {
    if (authLoading || !user) return;
    const skip = (page - 1) * pageSize;
    const params: Record<string, string> = {
      skip: String(skip),
      limit: String(pageSize),
    };
    if (statusFilter.size > 0) params.status = [...statusFilter].join(",");
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<PipelineRun>>("/api/v1/pipeline-runs", params);
        setRuns(data.items);
        setTotal(data.total);

        // Fetch missing ancestors so restart chains always root at the original run
        const pageIds = new Set(data.items.map((r) => r.id));
        const fetched = new Map<string, PipelineRun>();
        const toFetch = new Set<string>();
        for (const r of data.items) {
          if (r.restarted_from && !pageIds.has(r.restarted_from)) {
            toFetch.add(r.restarted_from);
          }
        }
        while (toFetch.size > 0) {
          const batch = [...toFetch];
          toFetch.clear();
          const results = await Promise.allSettled(
            batch.map((id) => apiGet<PipelineRun>(`/api/v1/pipeline-runs/${id}`))
          );
          for (const res of results) {
            if (res.status === "fulfilled") {
              const run = res.value;
              fetched.set(run.id, run);
              // Walk further up the chain if needed
              if (run.restarted_from && !pageIds.has(run.restarted_from) && !fetched.has(run.restarted_from)) {
                toFetch.add(run.restarted_from);
              }
            }
          }
        }
        setAncestors(fetched);
      } catch {
        setRuns([]);
        setAncestors(new Map());
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, statusFilterKey, page, pageSize]);

  // Fetch total count (all runs) once on mount
  useEffect(() => {
    if (authLoading || !user) return;
    apiGet<PaginatedResponse<PipelineRun>>("/api/v1/pipeline-runs", { skip: "0", limit: "0" })
      .then((data) => setTotalAll(data.total))
      .catch(() => setTotalAll(0));
  }, [user, authLoading]);

  // Reset to page 1 when filter or page size changes (adjust state during
  // render rather than in an effect — avoids an extra post-mount render).
  const resetKey = `${statusFilterKey}|${pageSize}`;
  const [prevResetKey, setPrevResetKey] = useState(resetKey);
  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey);
    setPage(1);
  }

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user) return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to view runs.</p>;

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
          {["pending", "running", "completed", "failed", "cancelled"].map((s) => (
            <button
              key={s}
              onClick={() => toggleStatus(s)}
              className={`rounded-full px-3 py-1 text-sm font-medium capitalize transition-colors ${
                statusFilter.has(s)
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : runs.length === 0 ? (
        <p className="mt-6 text-gray-500">No runs found.</p>
      ) : (
        <>
          <div className="mt-6 overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Run ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Pipeline</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Version</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Submitted By</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Submitted On</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {runTree.map(({ parent, children }) => (
                  <RunGroup key={parent.id} parent={parent} childRuns={children} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                Showing {(page - 1) * pageSize + 1}&ndash;{Math.min(page * pageSize, total)} of {total}
              </p>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-1.5">
                  <label htmlFor="page-size" className="text-sm text-gray-500">Rows</label>
                  <select
                    id="page-size"
                    value={pageSize}
                    onChange={(e) => setPageSize(Number(e.target.value))}
                    className="rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  >
                    {PAGE_SIZE_OPTIONS.map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>
                {buildPageNumbers(page, totalPages).map((p, i) =>
                  p === "..." ? (
                    <span key={`ellipsis-${i}`} className="px-1 text-gray-400">...</span>
                  ) : (
                    <button
                      key={p}
                      onClick={() => setPage(p as number)}
                      className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                        p === page
                          ? "bg-blue-600 text-white"
                          : "border border-gray-300 text-gray-700 hover:bg-gray-50"
                      }`}
                    >
                      {p}
                    </button>
                  ),
                )}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RunGroup({ parent, childRuns }: { parent: PipelineRun; childRuns: PipelineRun[] }) {
  return (
    <>
      <RunRow run={parent} />
      {childRuns.map((child) => (
        <RunRow key={child.id} run={child} isChild />
      ))}
    </>
  );
}

