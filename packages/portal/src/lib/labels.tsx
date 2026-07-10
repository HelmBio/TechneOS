"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { apiGet } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/**
 * Catalog of configurable UI label keys and their English defaults.
 *
 * A platform_admin can override any of these per AIRE instance via
 * /settings/labels (persisted in the backend `platform_settings` table). UI
 * code always resolves labels through `useLabel()` / `useLabels()`, which fall
 * back to the default here for any key without an override — so labels are
 * never blank, and unknown keys returned by the server are simply ignored.
 *
 * The dotted key structure (e.g. `resource.pipeline.plural`) is deliberately
 * i18n-message-key shaped, so this can migrate onto a real i18n framework
 * later without reworking call sites.
 *
 * Note: routes, DB tables, and `countKey`s stay `pipeline(s)` — only the
 * displayed string for that resource defaults to "Workflows".
 */
export const DEFAULT_LABELS = {
  "section.catalog": "Catalog",
  "section.executions": "Executions",
  "resource.dataset.plural": "Datasets",
  "resource.tool.plural": "Tools",
  "resource.task.plural": "Tasks",
  "resource.pipeline.plural": "Pipelines",
  "resource.app.plural": "Apps",
  "resource.agent.plural": "Agents",
  "exec.tool.plural": "Tool Jobs",
  "exec.task.plural": "Task Runs",
  "exec.pipeline.plural": "Pipeline Runs",
  "exec.agent.plural": "Agent Sessions",
} as const;

export type LabelKey = keyof typeof DEFAULT_LABELS;

/** All known label keys in display order (used by the admin editor). */
export const LABEL_KEYS = Object.keys(DEFAULT_LABELS) as LabelKey[];

type LabelsContextValue = {
  /** Resolve a label key to its overridden or default display string. */
  t: (key: LabelKey) => string;
  /** Raw override map from the server (unknown keys are kept but never read). */
  overrides: Record<string, string>;
  /** Re-fetch overrides — call after the admin saves changes. */
  refresh: () => Promise<void>;
};

const LabelsContext = createContext<LabelsContextValue>({
  t: (key) => DEFAULT_LABELS[key],
  overrides: {},
  refresh: async () => {},
});

export function LabelsProvider({ children }: { children: ReactNode }) {
  const { user, tokenVersion } = useAuth();
  const [overrides, setOverrides] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<{ overrides: Record<string, string> }>(
        "/api/v1/admin/labels",
      );
      setOverrides(data.overrides ?? {});
    } catch {
      // Labels are non-critical — fall back to in-code defaults on any error.
      setOverrides({});
    }
  }, []);

  // Fetch once the user is authenticated, and again after a token refresh.
  // Overrides are platform-wide (not user-specific), so there's no need to
  // clear them on logout — they're simply re-fetched on the next login.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    apiGet<{ overrides: Record<string, string> }>("/api/v1/admin/labels")
      .then((data) => {
        if (!cancelled) setOverrides(data.overrides ?? {});
      })
      .catch(() => {
        if (!cancelled) setOverrides({});
      });
    return () => {
      cancelled = true;
    };
  }, [user, tokenVersion]);

  const t = useCallback(
    (key: LabelKey): string => overrides[key] ?? DEFAULT_LABELS[key],
    [overrides],
  );

  return (
    <LabelsContext.Provider value={{ t, overrides, refresh }}>
      {children}
    </LabelsContext.Provider>
  );
}

/** Returns the full labels context: resolver `t`, raw `overrides`, `refresh`. */
export function useLabels() {
  return useContext(LabelsContext);
}

/** Convenience hook for a single static label: `useLabel("section.catalog")`. */
export function useLabel(key: LabelKey): string {
  return useContext(LabelsContext).t(key);
}
