"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import {
  apiGet,
  type AgenticRun,
  type AgenticTask,
  type AgentDefinition,
  type PaginatedResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { StatusBadge } from "@/components/run/status-badge";

interface AgenticRunWithTasks extends AgenticRun {
  tasks?: AgenticTask[];
}

export default function AgenticRunsPage() {
  const execLabel = useLabel("exec.agent.plural");
  const { user, loading: authLoading } = useAuth();
  const [runs, setRuns] = useState<AgenticRunWithTasks[]>([]);
  const [agents, setAgents] = useState<Map<string, AgentDefinition>>(new Map());
  const [total, setTotal] = useState(0);
  const [totalAll, setTotalAll] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set());
  const [loadingTasks, setLoadingTasks] = useState<Set<string>>(new Set());
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());

  function toggleAgent(agentId: string) {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) {
        next.delete(agentId);
      } else {
        next.add(agentId);
      }
      return next;
    });
  }

  useEffect(() => {
    if (authLoading || !user) return;
    setLoading(true);

    Promise.all([
      apiGet<PaginatedResponse<AgentDefinition>>("/api/v1/agents", { skip: "0", limit: "50", include_platform: "true" }),
      apiGet<PaginatedResponse<AgenticRun>>("/api/v1/agentic-runs", { skip: "0", limit: "100" }),
    ])
      .then(([agentData, runData]) => {
        const agentMap = new Map<string, AgentDefinition>();
        for (const a of agentData.items) {
          agentMap.set(a.id, a);
        }
        setAgents(agentMap);
        setRuns(runData.items);
        setTotal(runData.total);
      })
      .catch((e) => {
        console.error("Failed to fetch agentic runs:", e);
        setRuns([]);
      })
      .finally(() => setLoading(false));
  }, [user, authLoading]);

  // Fetch total count (all runs) once on mount
  useEffect(() => {
    if (authLoading || !user) return;
    apiGet<PaginatedResponse<AgenticRun>>("/api/v1/agentic-runs", { skip: "0", limit: "0" })
      .then((data) => setTotalAll(data.total))
      .catch(() => setTotalAll(0));
  }, [user, authLoading]);

  // Filtered runs (client-side based on selectedAgents)
  const filteredRuns = selectedAgents.size > 0
    ? runs.filter((r) => r.agent_id && selectedAgents.has(r.agent_id))
    : runs;

  async function toggleRun(runId: string) {
    const isExpanded = expandedRuns.has(runId);
    if (isExpanded) {
      setExpandedRuns((prev) => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
      return;
    }

    // Expand and fetch tasks if not already loaded
    setExpandedRuns((prev) => new Set(prev).add(runId));

    const run = runs.find((r) => r.id === runId);
    if (run?.tasks) return; // already loaded

    setLoadingTasks((prev) => new Set(prev).add(runId));
    try {
      const detail = await apiGet<AgenticRunWithTasks>(`/api/v1/agentic-runs/${runId}`);
      setRuns((prev) =>
        prev.map((r) => (r.id === runId ? { ...r, tasks: detail.tasks } : r))
      );
    } catch (e) {
      console.error("Failed to fetch tasks for run:", e);
    } finally {
      setLoadingTasks((prev) => {
        const next = new Set(prev);
        next.delete(runId);
        return next;
      });
    }
  }

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">log in</a>{" "}
        to view agentic runs.
      </p>
    );

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">
          {execLabel}
        <span className="ml-2 rounded-full bg-gray-100 px-2.5 py-0.5 text-sm font-semibold tabular-nums text-gray-600">
            {selectedAgents.size > 0
              ? `${filteredRuns.length} out of ${totalAll || 0}`
              : `${totalAll || 0}`}
        </span>
        </h1>
        <div className="flex items-center gap-2">
          {Array.from(agents.values()).map((agent) => (
            <button
              key={agent.id}
              onClick={() => toggleAgent(agent.id)}
              className={`rounded-full px-3 py-1 text-sm font-medium capitalize transition-colors ${
                selectedAgents.has(agent.id)
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {agent.name}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : filteredRuns.length === 0 ? (
        <div className="mt-8 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 py-16">
          <svg
            className="h-12 w-12 text-gray-300"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 0 0 2.25-2.25V6.75a2.25 2.25 0 0 0-2.25-2.25H6.75A2.25 2.25 0 0 0 4.5 6.75v10.5a2.25 2.25 0 0 0 2.25 2.25Zm.75-12h9v9h-9v-9Z"
            />
          </svg>
          <p className="mt-4 text-sm font-medium text-gray-500">No agentic runs found</p>
          <p className="mt-1 text-xs text-gray-400">Agentic runs will appear here once agents are executed.</p>
</div>
      ) : (
        <div className="mt-6 space-y-3">
          {filteredRuns.map((run) => {
              const agent = agents.get(run.agent_id ?? "");
              const isExpanded = expandedRuns.has(run.id);
              const isLoadingTasks = loadingTasks.has(run.id);

              return (
                <div key={run.id} className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
                {/* Run header */}
                <div
                  className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50"
                  onClick={() => toggleRun(run.id)}
                >
                  <svg
                    className={`h-4 w-4 text-gray-400 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                    stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/agents/${agent?.slug || run.agent_id}?run=${run.id}`}
                        className="text-xs font-medium text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full hover:bg-indigo-100"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {run.title || `Run ${run.id.slice(0, 8)}`}
                      </Link>
                      {agent && (
                        <Link
                          href={`/agents/${agent.id}`}
                          className="text-xs text-blue-600 hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {agent.name}
                        </Link>
                      )}
                      {!agent && !run.agent_id && (
                        <span className="text-xs text-purple-600 bg-purple-50 px-2 py-0.5 rounded-full">
                          Platform Assistant
                        </span>
                      )}
                    </div>
                    {run.summary && (
                      <p className="mt-1 text-sm text-gray-600 truncate">{run.summary}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {run.latest_task_status && (
                      <StatusBadge status={run.latest_task_status} />
                    )}
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                      {run.task_count} {run.task_count === 1 ? "turn" : "turns"}
                    </span>
                    <span className="text-xs text-gray-400">
                      {new Date(run.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>

                {/* Expanded tasks */}
                {isExpanded && (
                  <div className="border-t border-gray-100">
                    {isLoadingTasks ? (
                      <p className="px-4 py-3 text-sm text-gray-500">Loading tasks...</p>
                    ) : run.tasks && run.tasks.length > 0 ? (
                      <table className="min-w-full divide-y divide-gray-100">
                        <thead className="bg-gray-50/50">
                          <tr>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Task ID</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Task</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Tokens</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Time</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {run.tasks.map((task) => (
                            <tr key={task.id} className="hover:bg-gray-50/50">
                              <td className="px-4 py-2">
                                <span className="font-mono text-xs text-gray-600">
                                  {task.id.slice(0, 12)}...
                                </span>
                              </td>
                              <td className="px-4 py-2 text-sm text-gray-700 truncate max-w-xs">
                                {task.task || "—"}
                              </td>
                              <td className="px-4 py-2">
                                <StatusBadge status={task.status} />
                              </td>
                              <td className="px-4 py-2 text-xs text-gray-500">
                                {task.tokens_used ?? "—"}
                              </td>
                              <td className="px-4 py-2 text-xs text-gray-500">
                                {task.created_at ? new Date(task.created_at).toLocaleString() : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <p className="px-4 py-3 text-sm text-gray-500">No tasks in this run.</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
