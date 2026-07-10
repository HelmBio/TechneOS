"use client";

import { useEffect, useState, useCallback } from "react";
import {
  apiGet,
  apiPost,
  apiDelete,
  type Subscription,
  type PaginatedResponse,
} from "@/lib/api";

/**
 * Hook that loads all of the current user's subscriptions for a given
 * resource type and exposes lookup + follow/unfollow helpers.
 *
 * Usage:
 *   const { isFollowed, toggle, loading } = useSubscriptions("dataset");
 *   // in a row:  isFollowed(ds.id)  →  true/false
 *   //            toggle(ds.id)      →  follows or unfollows, updates local state
 */
export function useSubscriptions(resourceType: string) {
  // resource_id → subscription_id
  const [subMap, setSubMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<Subscription>>("/api/v1/subscriptions", {
          resource_type: resourceType,
          limit: "500",
        });
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const s of data.items) {
          map[s.resource_id] = s.id;
        }
        setSubMap(map);
      } catch {
        if (!cancelled) setSubMap({});
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [resourceType]);

  const isFollowed = useCallback(
    (resourceId: string): boolean => resourceId in subMap,
    [subMap]
  );

  const toggle = useCallback(
    async (resourceId: string) => {
      const subId = subMap[resourceId];
      if (subId) {
        // Unfollow
        await apiDelete(`/api/v1/subscriptions/${subId}`);
        setSubMap((prev) => {
          const next = { ...prev };
          delete next[resourceId];
          return next;
        });
      } else {
        // Follow
        const sub = await apiPost<Subscription>("/api/v1/subscriptions", {
          resource_type: resourceType,
          resource_id: resourceId,
        });
        setSubMap((prev) => ({ ...prev, [resourceId]: sub.id }));
      }
    },
    [subMap, resourceType]
  );

  return { isFollowed, toggle, loading } as const;
}
