"use client";

import { useState } from "react";
import { apiPatch, type PipelineWithVersions, type PipelineStepConfig } from "@/lib/api";
import { TOOL_CATEGORIES } from "@/lib/constants";
import PipelineGraph from "@/components/pipeline-graph";

const PIPELINE_TYPES = ["compute", "interactive", "hybrid"];

export function PipelineMetadataModal({
  pipeline,
  onClose,
  onUpdate,
}: {
  pipeline: PipelineWithVersions;
  onClose: () => void;
  onUpdate: () => void;
}) {
  const [description, setDescription] = useState(pipeline.description || "");
  const [category, setCategory] = useState(pipeline.category);
  const [pipelineType, setPipelineType] = useState(pipeline.pipeline_type);
  const [tags, setTags] = useState(pipeline.tags.join(", "));
  const [isPublic, setIsPublic] = useState(pipeline.is_public);
  const [readme, setReadme] = useState(pipeline.readme || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Declared run inputs (the x-input properties of the parameters_schema) — the
  // identity-relevant part of the run-I/O contract. Read-only: shape is locked.
  const schema = (pipeline.parameters_schema ?? {}) as Record<string, unknown>;
  const required = Array.isArray(schema.required) ? (schema.required as string[]) : [];
  const props = (schema.properties ?? {}) as Record<string, Record<string, unknown>>;
  const runInputs = Object.entries(props)
    .filter(([, spec]) => spec?.["x-input"])
    .map(([name, spec]) => ({
      name,
      type: typeof spec.type === "string" ? spec.type : undefined,
      step: typeof spec["x-step"] === "string" ? (spec["x-step"] as string) : undefined,
      required: required.includes(name),
    }));

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      // Metadata only. The DAG shape is part of the pipeline's identity and is
      // immutable once defined — shown locked above, never sent here.
      // Tool/param changes go through versions; topology changes go through fork.
      await apiPatch(`/api/v1/pipelines/${pipeline.id}`, {
        name: pipeline.name,
        description: description || null,
        category,
        pipeline_type: pipelineType,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        is_public: isPublic,
        readme: readme || null,
      });
      onUpdate();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Update Pipeline Definition</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">Name</label>
            <p className="mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{pipeline.name}</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Slug</label>
            <p className="mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{pipeline.slug}</p>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <label className="block text-sm font-medium text-gray-700">Pipeline DAG</label>
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                Locked
              </span>
            </div>
            <p className="mt-0.5 text-xs text-gray-500">
              The DAG is part of the pipeline&apos;s identity and is fixed once defined —
              like the name and slug. To change the topology, fork the pipeline.
            </p>
            {(pipeline.steps?.length ?? 0) > 0 ? (
              <div className="mt-1 rounded-md border border-gray-200 bg-gray-50 p-2">
                <PipelineGraph steps={pipeline.steps as unknown as PipelineStepConfig[]} />
              </div>
            ) : (
              <p className="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-500">
                No steps defined.
              </p>
            )}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <label className="block text-sm font-medium text-gray-700">Run inputs</label>
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                Locked
              </span>
            </div>
            <p className="mt-0.5 text-xs text-gray-500">
              The run-input contract is part of the pipeline&apos;s identity (an input&apos;s
              routing to a step is hashed into its topology). Fixed once defined.
            </p>
            {runInputs.length > 0 ? (
              <ul className="mt-1 divide-y divide-gray-100 rounded-md border border-gray-200 bg-gray-50">
                {runInputs.map((inp) => (
                  <li key={inp.name} className="flex items-center justify-between gap-2 px-3 py-1.5">
                    <span className="font-mono text-sm text-gray-700">
                      {inp.name}
                      {inp.required && <span className="ml-1 text-red-500" title="required">*</span>}
                    </span>
                    <span className="flex items-center gap-2 text-xs text-gray-500">
                      {inp.type && <span className="rounded bg-gray-200 px-1.5 py-0.5 font-mono">{inp.type}</span>}
                      {inp.step && <span>&rarr; {inp.step}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-500">
                No run inputs declared.
              </p>
            )}
            {Object.keys(pipeline.parameters_schema ?? {}).length > 0 && (
              <details className="mt-1">
                <summary className="cursor-pointer text-xs text-blue-600 hover:underline">
                  Show full parameters schema
                </summary>
                <pre className="mt-1 max-h-60 overflow-auto rounded bg-gray-50 p-3 text-xs">
                  {JSON.stringify(pipeline.parameters_schema, null, 2)}
                </pre>
              </details>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700">Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {TOOL_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Type</label>
              <select
                value={pipelineType}
                onChange={(e) => setPipelineType(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {PIPELINE_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Tags</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="comma-separated, e.g. docking, virtual-screening"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">README (Markdown)</label>
            <textarea
              value={readme}
              onChange={(e) => setReadme(e.target.value)}
              rows={8}
              placeholder="# Pipeline name&#10;&#10;What it does, its inputs/outputs, and how to use it..."
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Public pipeline (visible to all organizations)
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
