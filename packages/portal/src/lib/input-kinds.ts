import type { ToolRun } from "@/lib/api";

/**
 * The three input modes a tool run can carry. Mirrors the platform's
 * typed-pointer shape stamped into `ToolRun.parameters` by the
 * submit-run handler — see `_move_inputs_to_canonical_prefix` and the
 * typed-pointer rewrite in
 * `packages/services/tool/src/tool_service/routes/runs.py`.
 */
export const INPUT_TYPE_KINDS = ["paste", "upload", "dataset"] as const;

export type InputTypeKind = (typeof INPUT_TYPE_KINDS)[number];

/**
 * Tailwind pill classes per kind. Co-located with the kind list so the
 * Input Type column on every table renders identically.
 */
export const INPUT_TYPE_COLORS: Record<InputTypeKind, string> = {
  paste: "bg-purple-100 text-purple-800",
  upload: "bg-amber-100 text-amber-800",
  dataset: "bg-teal-100 text-teal-800",
};

// `<slug>:v<N>` — the legacy dataset reference shape.
const LEGACY_DATASET_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*:v\d+$/;

/**
 * Scan a run's parameters for typed-pointer values and return the
 * unique input kinds found.
 *
 * Current shape (since the unified-input-modes change) is:
 *   { type: "paste"|"upload"|"dataset", ... }
 *
 * Older in-flight runs may still carry the legacy string shapes that
 * this function also handles so columns stay correct:
 *   "upload:<id>"   → upload
 *   "<slug>:v<N>"   → dataset
 * (Pre-change paste was inlined as a list and has no detectable
 * shape — those runs naturally render as "—".)
 *
 * Tools with only scalar params (booleans, strings, numbers) return
 * an empty array. Tools that mix sources return one entry per kind.
 */
export function inputKindsFor(run: ToolRun): InputTypeKind[] {
  const found = new Set<InputTypeKind>();
  for (const value of Object.values(run.parameters ?? {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const t = (value as { type?: unknown }).type;
      if (typeof t === "string" && (INPUT_TYPE_KINDS as readonly string[]).includes(t)) {
        found.add(t as InputTypeKind);
      }
    } else if (typeof value === "string") {
      if (value.startsWith("upload:")) {
        found.add("upload");
      } else if (LEGACY_DATASET_RE.test(value)) {
        found.add("dataset");
      }
    }
  }
  return [...found];
}
