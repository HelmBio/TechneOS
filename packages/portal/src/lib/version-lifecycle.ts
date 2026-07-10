// Version-status lifecycle policy for tool/task and pipeline versions.
//
// Mirrors the backend single source of truth in
// packages/core/src/core/version_lifecycle.py. Keep the transition map and the
// edit-lock rule in sync with that module.

export const VERSION_STATUSES = ["draft", "testing", "active", "deprecated"] as const;
export type VersionStatus = (typeof VERSION_STATUSES)[number];

export const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  testing: "bg-yellow-100 text-yellow-800",
  active: "bg-green-100 text-green-800",
  deprecated: "bg-red-100 text-red-700",
};

// Directed transition map: each status maps to the statuses it may move to.
// Same-status (no-op) is always permitted and handled in nextStatusOptions.
// Deprecation is only reachable from `active`: a version must progress through
// draft -> testing -> active before it can be deprecated.
export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  draft: ["testing"],
  testing: ["draft", "active"],
  active: ["deprecated"],
  deprecated: ["active"], // restore
};

// Statuses whose definition may still be edited in place (subject to having no
// runs — see definitionEditable).
const EDITABLE_STATUSES = new Set(["draft", "testing"]);

/**
 * Options to offer in the status <select>: the current status plus every legal
 * target, in canonical order. The current status stays selectable so the
 * control can render its own value even when no transition is chosen.
 */
export function nextStatusOptions(current: string): string[] {
  const targets = new Set<string>([current, ...(ALLOWED_TRANSITIONS[current] ?? [])]);
  return VERSION_STATUSES.filter((s) => targets.has(s));
}

/**
 * Whether a version's definition may be edited in place. Editable only while
 * the version is draft/testing and has no recorded runs; once active/deprecated
 * or run-backed, the definition is frozen and a new version must be created.
 */
export function definitionEditable(status: string, hasRuns: boolean | undefined): boolean {
  return EDITABLE_STATUSES.has(status) && !hasRuns;
}
