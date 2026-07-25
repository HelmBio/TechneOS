"use client";

import { useEffect, useMemo, useState } from "react";
import {
  apiGet,
  apiPatch,
  apiPost,
  type PipelineVersion,
  type PipelineWithVersions,
  type ToolWithVersions,
} from "@/lib/api";
import { SchemaParamControl, defaultForProp } from "@/components/pipeline/param-field";

type StepBinding = {
  name: string;
  tool_slug: string;
  depends_on: string[];
  tool_version: string; // "" = latest active
  params: Record<string, unknown>;
};

type VersionInfo = {
  version: number;
  status: string;
  parameters_schema: Record<string, unknown>;
};

/**
 * New-version editor for a pipeline, as a modal (mirrors ToolVersionEditorModal).
 * A version is a *binding* over the pipeline's fixed shape: the DAG —
 * step names, tools, and dependencies — is locked; only the tool-version pin and
 * the exposed parameters/defaults per step are editable.
 */
export function PipelineVersionEditorModal({
  pipeline,
  version,
  onClose,
  onComplete,
}: {
  pipeline: PipelineWithVersions;
  /** When set, edit this draft/testing version in place; otherwise create a new one. */
  version?: PipelineVersion | null;
  onClose: () => void;
  onComplete: () => void;
}) {
  const editing = !!version;
  const latest = useMemo(
    () => [...(pipeline.versions || [])].sort((a, b) => b.version - a.version)[0],
    [pipeline.versions],
  );
  // Edit → seed/prefill from the target version; create → from the latest.
  const source = version ?? latest;

  // Per-step schema attached to the source version's effective steps (resolved
  // server-side from each pinned tool version) — seeds the editor immediately.
  const seedSchema = useMemo(() => {
    const m: Record<string, Record<string, unknown>> = {};
    for (const s of (source?.steps ?? []) as Record<string, unknown>[]) {
      if (s.name) m[s.name as string] = (s.parameters_schema as Record<string, unknown>) ?? {};
    }
    return m;
  }, [source]);

  const [steps, setSteps] = useState<StepBinding[]>(() => {
    const sourceSteps = (source?.steps ?? []) as Record<string, unknown>[];
    const byName = new Map(sourceSteps.map((s) => [s.name as string, s]));
    return ((pipeline.steps ?? []) as Record<string, unknown>[]).map((ss) => {
      const b = byName.get(ss.name as string);
      return {
        name: ss.name as string,
        tool_slug: (ss.tool_slug as string) ?? "",
        depends_on: ((ss.depends_on as string[]) ?? []).filter(Boolean),
        tool_version: b?.tool_version != null ? String(b.tool_version) : "",
        params: (b?.parameters as Record<string, unknown>) ?? {},
      };
    });
  });

  const [changelog, setChangelog] = useState(version?.changelog ?? "");
  const [versionsBySlug, setVersionsBySlug] = useState<Record<string, VersionInfo[]>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Fetch each referenced tool's versions (for the pin dropdown + the schema
  // when the pin changes). One request per distinct tool.
  useEffect(() => {
    const slugs = [...new Set(steps.map((s) => s.tool_slug).filter(Boolean))];
    slugs.forEach((slug) => {
      apiGet<ToolWithVersions>(`/api/v1/tools/by-slug/${slug}`)
        .then((tool) =>
          setVersionsBySlug((prev) => ({
            ...prev,
            [slug]: (tool.versions ?? []).map((v) => ({
              version: v.version,
              status: v.status,
              parameters_schema: v.parameters_schema ?? {},
            })),
          })),
        )
        .catch(() => {});
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Schema properties for a step's currently-pinned tool version.
  const schemaProps = (step: StepBinding): Record<string, Record<string, unknown>> => {
    const versions = versionsBySlug[step.tool_slug];
    let schema: Record<string, unknown> | undefined;
    if (versions) {
      const v = step.tool_version
        ? versions.find((x) => String(x.version) === step.tool_version)
        : versions.filter((x) => x.status === "active").sort((a, b) => b.version - a.version)[0];
      schema = v?.parameters_schema;
    }
    schema = schema ?? seedSchema[step.name] ?? {};
    return ((schema.properties ?? {}) as Record<string, Record<string, unknown>>) ?? {};
  };

  const patchStep = (i: number, patch: Partial<StepBinding>) =>
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));

  const setParam = (i: number, key: string, value: unknown) =>
    setSteps((prev) =>
      prev.map((s, idx) => {
        if (idx !== i) return s;
        const params = { ...s.params };
        if (value === undefined) delete params[key];
        else params[key] = value;
        return { ...s, params };
      }),
    );

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      const bindings: Record<
        string,
        { tool_version: number | null; parameters: Record<string, unknown> }
      > = {};
      for (const s of steps) {
        bindings[s.name] = {
          tool_version: s.tool_version ? Number(s.tool_version) : null,
          parameters: s.params,
        };
      }
      const body = { bindings, changelog: changelog.trim() || null };
      if (editing && version) {
        await apiPatch(`/api/v1/pipelines/${pipeline.id}/versions/${version.id}`, body);
      } else {
        await apiPost(`/api/v1/pipelines/${pipeline.id}/versions`, body);
      }
      onComplete();
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : editing
            ? "Failed to update version"
            : "Failed to create version",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-3xl max-h-[95vh] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {editing ? `${pipeline.name} v${version!.version}: Update Version` : `${pipeline.name}: New Version`}
            </h2>
            <p className="mt-0.5 text-sm text-gray-500">
              {editing
                ? "Edit this draft/testing version's tool pins and parameters. The DAG is locked."
                : "A new version pins tool versions and parameters over the pipeline's locked DAG. To change the topology, fork the pipeline."}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>

        <div className="space-y-3">
          {steps.map((step, i) => {
            const props = schemaProps(step);
            const propKeys = Object.keys(props);
            const activeVersions = (versionsBySlug[step.tool_slug] ?? []).filter(
              (v) => v.status === "active",
            );
            return (
              <div key={step.name} className="rounded-lg border border-gray-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-[10px] font-bold text-blue-700">
                      {i + 1}
                    </span>
                    <span className="text-sm font-medium text-gray-900">{step.name}</span>
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-500">
                      {step.tool_slug}
                    </span>
                  </div>
                  <label className="flex items-center gap-1 text-xs text-gray-500">
                    version
                    <select
                      value={step.tool_version}
                      onChange={(e) => patchStep(i, { tool_version: e.target.value })}
                      className="rounded-md border border-gray-300 px-2 py-1 text-xs"
                    >
                      <option value="">latest active</option>
                      {activeVersions
                        .sort((a, b) => b.version - a.version)
                        .map((v) => (
                          <option key={v.version} value={String(v.version)}>
                            v{v.version}
                          </option>
                        ))}
                    </select>
                  </label>
                </div>
                {step.depends_on.length > 0 && (
                  <p className="mt-1 text-xs text-gray-400">
                    depends on: {step.depends_on.join(", ")}
                  </p>
                )}

                {propKeys.length === 0 ? (
                  <p className="mt-2 text-xs text-gray-400">No tunable parameters.</p>
                ) : (
                  <div className="mt-2">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-xs font-medium text-gray-600">Parameters</span>
                      <span className="text-[10px] text-gray-400">
                        check to expose in the run form
                      </span>
                    </div>
                    <div className="divide-y divide-gray-100 rounded-md border border-gray-200">
                      {propKeys.map((key) => {
                        const def = props[key] ?? {};
                        const exposed = key in step.params;
                        return (
                          <div key={key} className="flex items-start gap-2 px-3 py-2">
                            <input
                              type="checkbox"
                              checked={exposed}
                              onChange={() =>
                                exposed
                                  ? setParam(i, key, undefined)
                                  : setParam(i, key, defaultForProp(def))
                              }
                              className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs text-gray-800">{key}</span>
                                {def.type != null && (
                                  <span className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[10px] text-gray-500">
                                    {String(def.type)}
                                  </span>
                                )}
                              </div>
                              {def.description != null && (
                                <p className="text-[11px] text-gray-400">
                                  {String(def.description)}
                                </p>
                              )}
                              {exposed && (
                                <div className="mt-1">
                                  <SchemaParamControl
                                    propDef={def}
                                    value={step.params[key]}
                                    onChange={(v) => setParam(i, key, v)}
                                    placeholder={
                                      def.default != null
                                        ? `default: ${String(def.default)}`
                                        : "no default"
                                    }
                                    compact
                                  />
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Changelog <span className="text-xs font-normal text-gray-400">optional</span>
            </label>
            <textarea
              value={changelog}
              onChange={(e) => setChangelog(e.target.value)}
              rows={2}
              placeholder="What changed in this version — e.g. bumped autodock-vina to v2, raised exhaustiveness."
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        <div className="mt-4 flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving
              ? editing
                ? "Saving..."
                : "Creating..."
              : editing
                ? "Save Changes"
                : "Create Version"}
          </button>
          <button
            onClick={onClose}
            className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
