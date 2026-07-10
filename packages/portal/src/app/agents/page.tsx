"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet, type AgentDefinition, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLabel } from "@/lib/labels";
import { useSubscriptions } from "@/lib/use-subscriptions";
import { hasPermission } from "@/lib/rbac";
import { FollowIconButton } from "@/components/follow-icon-button";
import { ResourceCard } from "@/components/resource-card";
import { NewResourceButton } from "@/components/new-resource-button";

export default function AgentsPage() {
  const agentsLabel = useLabel("resource.agent.plural");
  const { user, loading: authLoading, permissions } = useAuth();
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const { isFollowed, toggle } = useSubscriptions("agent");

  useEffect(() => {
    if (authLoading || !user) return;
    const params: Record<string, string> = { skip: "0", limit: "50" };
    if (search) params.q = search;
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<AgentDefinition>>("/api/v1/agents", params);
        setAgents(data.items);
        setTotal(data.total);
      } catch {
        setAgents([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [user, authLoading, search]);

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>{" "}
        to view agents.
      </p>
    );

  return (
    <div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-gray-900">{agentsLabel}</h1>
          {total > 0 && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
              {total}
            </span>
          )}
        </div>
        {hasPermission(permissions, "agent", "create", "*") && <NewResourceButton href="/agents/new" tooltip="Build and register a new AI agent" />}
      </div>

      {total > 10 && (
        <input
          type="text"
          placeholder="Search agents..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mt-4 block w-full max-w-md rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      )}

      {loading ? (
        <p className="mt-6 text-gray-500">Loading...</p>
      ) : agents.length === 0 ? (
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
              d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"
            />
          </svg>
          <p className="mt-4 text-sm font-medium text-gray-500">
            No agents found
          </p>
          <p className="mt-1 text-xs text-gray-400">
            Agents will appear here once they are registered.
          </p>
        </div>
      ) : agents.length <= 10 ? (
        <div className="mt-6 grid gap-6 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {agents.map((agent) => (
            <ResourceCard
              key={agent.id}
              name={agent.name}
              description={agent.description}
              tags={agent.tags}
              href={`/agents/${agent.slug}`}
              isFollowed={isFollowed(agent.id)}
              onToggleFollow={() => toggle(agent.id)}
              metadata={[
                { label: "Tools", value: agent.tools.length },
                { label: "Created", value: new Date(agent.created_at).toLocaleDateString() },
              ]}
              badges={
                <>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">{agent.org_name || agent.org_id}</span>
                  {agent.is_public && <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Public</span>}
                  <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">{agent.agent_type}</span>
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs">{agent.framework}</span>
                </>
              }
            />
          ))}
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Framework</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Tools</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Creator</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Organization</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Public</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {agents.map((agent) => (
                <tr key={agent.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <Link href={`/agents/${agent.slug}`} className="font-medium text-blue-600 hover:underline">
                        {agent.name}
                      </Link>
                      <FollowIconButton
                        followed={isFollowed(agent.id)}
                        onClick={() => toggle(agent.id)}
                      />
                    </div>
                    {agent.description && (
                      <p className="text-xs text-gray-500 truncate max-w-xs">{agent.description}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{agent.agent_type}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{agent.framework}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{agent.tools.length}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{agent.creator_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{agent.org_name ?? "—"}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{agent.is_public ? "Yes" : "No"}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(agent.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
