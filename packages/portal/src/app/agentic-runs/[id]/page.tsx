"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { apiGet, type AgenticRun, type AgenticTask, type AgentDefinition } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { StatusBadge } from "@/components/run/status-badge";

interface AgenticRunDetailResponse extends AgenticRun {
  tasks: AgenticTask[];
}

export default function AgenticRunDetailPage() {
  const execLabel = useLabel("exec.agent.plural");
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading } = useAuth();
  const [run, setRun] = useState<AgenticRunDetailResponse | null>(null);
  const [agentName, setAgentName] = useState<string | null>(null);
  const [agentSlug, setAgentSlug] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading || !user || !id) return;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<AgenticRunDetailResponse>(`/api/v1/agentic-runs/${id}`);
        setRun(data);
        if (data.agent_id) {
          try {
            const agent = await apiGet<AgentDefinition>(`/api/v1/agents/${data.agent_id}`);
            setAgentName(agent.name);
            setAgentSlug(agent.slug);
          } catch {
            // Agent lookup is best-effort; run detail still renders without it.
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load agentic run");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, user, authLoading]);

  if (authLoading || loading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please <a href="/login" className="text-blue-600 underline">log in</a> to view this run.
      </p>
    );
  if (error || !run)
    return (
      <div className="p-8">
        <p className="text-red-600">{error || "Agentic run not found."}</p>
        <Link href="/agentic-runs" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
          &larr; Back to {execLabel}
        </Link>
      </div>
    );

  return (
    <div className="mx-auto max-w-4xl">
      {/* Header */}
      <div className="mb-6">
        <Link href="/agentic-runs" className="text-sm text-blue-600 hover:underline">
          &larr; {execLabel}
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-gray-900">Agentic Run</h1>
        </div>
        <p className="mt-1 font-mono text-sm text-gray-500">{run.id}</p>
        {run.title && <p className="mt-1 text-sm text-gray-700">{run.title}</p>}
      </div>

      {/* Info grid */}
      <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <dl className="divide-y divide-gray-200">
          <div className="grid grid-cols-3 px-4 py-3">
            <dt className="text-sm font-medium text-gray-500">Agent</dt>
            <dd className="col-span-2 text-sm text-gray-900">
              {run.agent_id ? (
                <Link href={`/agents/${agentSlug || run.agent_id}`} className="text-blue-600 hover:underline">
                  {agentName || run.agent_id}
                </Link>
              ) : (
                <span className="text-gray-500">—</span>
              )}
            </dd>
          </div>
          {run.summary && (
            <div className="grid grid-cols-3 px-4 py-3">
              <dt className="text-sm font-medium text-gray-500">Summary</dt>
              <dd className="col-span-2 text-sm text-gray-900 whitespace-pre-wrap">{run.summary}</dd>
            </div>
          )}
          <div className="grid grid-cols-3 px-4 py-3">
            <dt className="text-sm font-medium text-gray-500">Tasks</dt>
            <dd className="col-span-2 text-sm text-gray-900">{run.tasks.length}</dd>
          </div>
          <div className="grid grid-cols-3 px-4 py-3">
            <dt className="text-sm font-medium text-gray-500">Created</dt>
            <dd className="col-span-2 text-sm text-gray-900">
              {new Date(run.created_at).toLocaleString()}
            </dd>
          </div>
        </dl>
      </div>

      {/* Tasks */}
      {run.tasks.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-3 text-lg font-semibold text-gray-900">Tasks</h2>
          <div className="space-y-4">
            {run.tasks.map((task) => (
              <div key={task.id} className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
                <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
                  <StatusBadge status={task.status} />
                  <span className="font-mono text-xs text-gray-500">{task.id.slice(0, 12)}...</span>
                  <span className="ml-auto text-xs text-gray-400">
                    {task.created_at ? new Date(task.created_at).toLocaleString() : ""}
                  </span>
                </div>

                <div className="px-4 py-3">
                  <p className="text-sm text-gray-900 whitespace-pre-wrap">{task.task}</p>
                </div>

                {task.tokens_used != null && (
                  <div className="px-4 pb-2 text-xs text-gray-500">
                    Tokens: {task.tokens_used}
                  </div>
                )}

                {task.error_message && (
                  <div className="px-4 pb-3">
                    <p className="text-sm text-red-600 whitespace-pre-wrap">{task.error_message}</p>
                  </div>
                )}

                {/* Result */}
                {task.result && Object.keys(task.result).length > 0 && (
                  <div className="border-t border-gray-100 px-4 py-3">
                    <p className="mb-1 text-xs font-medium text-gray-500 uppercase">Result</p>
                    <pre className="overflow-x-auto rounded bg-gray-50 p-2 text-xs text-gray-800">
                      {JSON.stringify(task.result, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Messages */}
                {task.messages && task.messages.length > 0 && (
                  <div className="border-t border-gray-100 px-4 py-3">
                    <p className="mb-2 text-xs font-medium text-gray-500 uppercase">Messages</p>
                    <div className="space-y-2">
                      {task.messages.map((msg, i) => {
                        const role = (msg as Record<string, unknown>).role as string | undefined;
                        const content = (msg as Record<string, unknown>).content as string | undefined;
                        return (
                          <div
                            key={i}
                            className={`rounded border p-2 text-sm ${
                              role === "user"
                                ? "border-blue-200 bg-blue-50"
                                : role === "assistant"
                                  ? "border-gray-200 bg-white"
                                  : "border-gray-200 bg-gray-50"
                            }`}
                          >
                            <p className="mb-0.5 text-xs font-medium uppercase text-gray-500">
                              {role || "system"}
                            </p>
                            <p className="whitespace-pre-wrap text-gray-800">{content || JSON.stringify(msg)}</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Tool Calls */}
                {task.tool_calls && task.tool_calls.length > 0 && (
                  <div className="border-t border-gray-100 px-4 py-3">
                    <p className="mb-2 text-xs font-medium text-gray-500 uppercase">Tool Calls</p>
                    <div className="space-y-2">
                      {task.tool_calls.map((tc, i) => {
                        const call = tc as Record<string, unknown>;
                        return (
                          <div key={i} className="rounded border border-gray-200 bg-gray-50 p-2">
                            <p className="text-sm font-medium text-gray-900">
                              {(call.name as string) || `Tool Call ${i + 1}`}
                            </p>
                            {!!call.args && (
                              <pre className="mt-1 text-xs text-gray-600 overflow-x-auto">
                                {JSON.stringify(call.args, null, 2)}
                              </pre>
                            )}
                            {!!call.result && (
                              <pre className="mt-1 text-xs text-green-700 overflow-x-auto">
                                {typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2)}
                              </pre>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
