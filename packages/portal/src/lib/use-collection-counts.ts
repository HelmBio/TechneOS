"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, type PaginatedResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Asset types whose totals we track. */
const COLLECTIONS = ["datasets", "tools", "tasks", "pipelines", "pipeline-runs", "tool-runs", "agents", "agentic-runs", "apps", "task_runs"] as const;
export type Collection = (typeof COLLECTIONS)[number];

export type CollectionCounts = Record<Collection, number | null>;

const EMPTY: CollectionCounts = {
  datasets: null,
  tools: null,
  tasks: null,
  pipelines: null,
  "pipeline-runs": null,
  "tool-runs": null,
  agents: null,
  "agentic-runs": null,
  apps: null,
  task_runs: null,
};

/** How often (ms) to auto-refresh counts. */
const REFRESH_INTERVAL = 30_000;

/**
 * Fetches the total count for each collection via `GET /api/v1/{collection}?limit=1`.
 * Returns `null` per-collection while loading or on error.
 *
 * Automatically refreshes every 30 seconds and exposes a manual `refresh()`
 * callback so other pages (e.g. run list) can trigger an update.
 */
export function useCollectionCounts(): CollectionCounts & { refresh: () => void } {
  const { user, loading: authLoading } = useAuth();
  const [counts, setCounts] = useState<CollectionCounts>(EMPTY);
  const cancelledRef = useRef(false);

  // Reset counts on sign-out so stale data isn't shown (adjust state during
  // render rather than in an effect — avoids an extra post-mount render).
  const authKey = `${!!user}:${authLoading}`;
  const [prevAuthKey, setPrevAuthKey] = useState(authKey);
  if (authKey !== prevAuthKey) {
    setPrevAuthKey(authKey);
    if (!user && !authLoading) setCounts(EMPTY);
  }

  const fetchCounts = useCallback(() => {
    if (!user) return;

    const endpoints: Record<Collection, string> = {
      datasets: "/api/v1/datasets",
      tools: "/api/v1/tools",
      tasks: "/api/v1/tools?tool_type=human",
      pipelines: "/api/v1/pipelines",
      "pipeline-runs": "/api/v1/pipeline-runs",
      "tool-runs": "/api/v1/tool-runs",
      agents: "/api/v1/agents",
      "agentic-runs": "/api/v1/agentic-runs",
      apps: "/api/v1/apps",
      task_runs: "/api/v1/task-runs",
    };

    Promise.all(
      COLLECTIONS.map(async (key) => {
        try {
          const data = await apiGet<PaginatedResponse<unknown>>(endpoints[key], {
            skip: "0",
            limit: "1",
          });
          return [key, data.total] as const;
        } catch {
          return [key, null] as const;
        }
      })
    ).then((results) => {
      if (cancelledRef.current) return;
      const next = { ...EMPTY };
      for (const [key, total] of results) {
        next[key] = total;
      }
      setCounts(next);
    });
  }, [user]);

  // Initial fetch
  useEffect(() => {
    if (authLoading || !user) return;
    cancelledRef.current = false;
    fetchCounts();
    return () => {
      cancelledRef.current = true;
    };
  }, [user, authLoading, fetchCounts]);

  // Periodic refresh
  useEffect(() => {
    if (authLoading || !user) return;
    const id = setInterval(fetchCounts, REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, [user, authLoading, fetchCounts]);

  return { ...counts, refresh: fetchCounts };
}
