"use client";

import { useState } from "react";
import { apiPatch, type ToolWithVersions } from "@/lib/api";
import { TOOL_CATEGORIES } from "@/lib/constants";

const TOOL_TYPES = ["container", "module", "pypi", "api", "human"];

export function ToolMetadataModal({
  tool,
  kind = "tool",
  onClose,
  onUpdate,
}: {
  tool: ToolWithVersions;
  kind?: "tool" | "task";
  onClose: () => void;
  onUpdate: () => void;
}) {
  const [description, setDescription] = useState(tool.description || "");
  const [category, setCategory] = useState(tool.category);
  const [toolType, setToolType] = useState(tool.tool_type);
  const [tags, setTags] = useState(tool.tags.join(", "));
  const [isPublic, setIsPublic] = useState(tool.is_public);
  const [readme, setReadme] = useState(tool.readme || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const label = kind === "task" ? "Task" : "Tool";

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await apiPatch(`/api/v1/tools/${tool.id}`, {
        name: tool.name,
        description: description || null,
        category,
        tool_type: toolType,
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
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Update {label} Definition</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">Name</label>
            <p className="mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{tool.name}</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Slug</label>
            <p className="mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{tool.slug}</p>
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
          <div className={kind === "task" ? "" : "grid grid-cols-2 gap-3"}>
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
            {kind !== "task" && (
              <div>
                <label className="block text-sm font-medium text-gray-700">Tool Type</label>
                <select
                  value={toolType}
                  onChange={(e) => setToolType(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {TOOL_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Tags</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="comma-separated, e.g. docking, admet, virtual-screening"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">README (Markdown)</label>
            <textarea
              value={readme}
              onChange={(e) => setReadme(e.target.value)}
              rows={8}
              placeholder={kind === "task"
                ? "# Task name&#10;&#10;What it involves, SOPs, expected outputs..."
                : "# Tool name&#10;&#10;What it does, how to use it, expected inputs/outputs..."}
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
            Public {label.toLowerCase()} (visible to all organizations)
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
