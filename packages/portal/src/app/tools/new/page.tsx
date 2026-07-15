"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import {
  apiGet,
  apiPost,
  apiPatch,
  type ToolWithVersions,
  type Tool,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { TOOL_CATEGORIES } from "@/lib/constants";

const CATEGORIES = TOOL_CATEGORIES;
// Note: "module" is not a supported tool_type. Register such tools as "pypi"
// (publish a wheel with run(inputs, params) -> dict).
const TOOL_TYPES = ["container", "pypi", "api"];
const TYPE_DESCRIPTIONS: Record<string, string> = {
  container: "A Docker container image (dedicated container per execution)",
  pypi: "Python package installed from a package index (PyPI / DevPI / CodeArtifact)",
  api: "An external API endpoint (Docker container wrapping an HTTP service)",
};

interface ToolFormData {
  name: string;
  slug: string;
  description: string;
  category: string;
  tool_type: string;
  tags: string;
  is_public: boolean;
  readme: string;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export default function Page() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-500">Loading...</div>}>
      <ToolFormPage />
    </Suspense>
  );
}

function ToolFormPage() {
  const toolsLabel = useLabel("resource.tool.plural");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading } = useAuth();

  // Mode detection. Tools are not duplicable — a tool is backed by a compute
  // artifact (a published wheel or image), so a copied definition would dangle
  // against the original's artifact. Create a fresh tool instead.
  const editId = searchParams.get("edit"); // edit
  const mode = editId ? "edit" : "create";
  const sourceId = editId;

  const [loading, setLoading] = useState(!!sourceId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slugManual, setSlugManual] = useState(false);

  // Tool form
  const [tool, setTool] = useState<ToolFormData>({
    name: "",
    slug: "",
    description: "",
    category: "general",
    tool_type: "container",
    tags: "",
    is_public: false,
    readme: "",
  });

  // Load source tool for edit
  useEffect(() => {
    if (!sourceId || authLoading || !user) return;
    setLoading(true);
    apiGet<ToolWithVersions>(`/api/v1/tools/${sourceId}`)
      .then((data) => {
        const tags = data.tags.join(", ");
        setTool({
          name: data.name,
          slug: data.slug,
          description: data.description || "",
          category: data.category,
          tool_type: data.tool_type,
          tags,
          is_public: data.is_public,
          readme: data.readme || "",
        });
        setSlugManual(true);
      })
      .catch(() => setError("Failed to load tool"))
      .finally(() => setLoading(false));
  }, [sourceId, authLoading, user, mode]);

  // Auto-slug from name
  const handleNameChange = (name: string) => {
    setTool((prev) => ({
      ...prev,
      name,
      slug: slugManual ? prev.slug : slugify(name),
    }));
  };

  const handleSubmit = async () => {
    setError(null);
    setSaving(true);

    try {
      if (mode === "edit") {
        await apiPatch(`/api/v1/tools/${editId}`, {
          name: tool.name,
          description: tool.description || null,
          category: tool.category,
          tool_type: tool.tool_type,
          tags: tool.tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
          is_public: tool.is_public,
          readme: tool.readme || null,
        });
        router.push(`/tools/${editId}`);
      } else {
        const tags = tool.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean);
        const created = await apiPost<Tool>("/api/v1/tools", {
          name: tool.name,
          slug: tool.slug,
          description: tool.description || null,
          category: tool.category,
          tool_type: tool.tool_type,
          tags,
          is_public: tool.is_public,
          readme: tool.readme || null,
        });
        router.push(`/tools/${created.id}`);
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to save tool";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  if (authLoading)
    return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>{" "}
        to manage tools.
      </p>
    );
  if (loading)
    return <p className="p-8 text-gray-500">Loading tool...</p>;

  return (
    <div className="max-w-3xl space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/tools" className="hover:text-blue-600">
          {toolsLabel}
        </Link>
        <span>/</span>
        <span>{mode === "edit" ? "Update Tool" : "New Tool Definition"}</span>
      </div>

      <h1 className="text-2xl font-bold text-gray-900">
        {mode === "edit" ? "Update Tool" : "Register New Tool Definition"}
      </h1>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ── Tool Metadata ─────────────────────────────────────── */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm space-y-4">

        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Name *
          </label>
          <input
            type="text"
            value={tool.name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g. ADMET Predictor"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Slug */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Slug *
          </label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={tool.slug}
              onChange={(e) => {
                setSlugManual(true);
                setTool((prev) => ({ ...prev, slug: e.target.value }));
              }}
              disabled={mode === "edit"}
              placeholder="e.g. admet-predictor"
              className={`block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                mode === "edit" ? "bg-gray-100 text-gray-500" : ""
              }`}
            />
            {mode !== "edit" && slugManual && (
              <button
                type="button"
                onClick={() => {
                  setSlugManual(false);
                  setTool((prev) => ({
                    ...prev,
                    slug: slugify(prev.name),
                  }));
                }}
                className="whitespace-nowrap text-xs text-blue-600 hover:underline"
              >
                Auto
              </button>
            )}
          </div>
          {mode === "edit" && (
            <p className="mt-1 text-xs text-gray-500">
              Slug cannot be changed after creation.
            </p>
          )}
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Description
          </label>
          <textarea
            value={tool.description}
            onChange={(e) =>
              setTool((prev) => ({
                ...prev,
                description: e.target.value,
              }))
            }
            placeholder="Describe what this tool does..."
            rows={3}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Category + Type row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Category
            </label>
            <select
              value={tool.category}
              onChange={(e) =>
                setTool((prev) => ({
                  ...prev,
                  category: e.target.value,
                }))
              }
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Type
            </label>
            <select
              value={tool.tool_type}
              onChange={(e) =>
                setTool((prev) => ({
                  ...prev,
                  tool_type: e.target.value,
                }))
              }
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {TOOL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-gray-500">
              {TYPE_DESCRIPTIONS[tool.tool_type]}
            </p>
          </div>
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Tags
          </label>
          <input
            type="text"
            value={tool.tags}
            onChange={(e) =>
              setTool((prev) => ({ ...prev, tags: e.target.value }))
            }
            placeholder="comma-separated, e.g. admet, toxicity, lipinski"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* README — Markdown documentation for the tool (was on each
            version before; moved to the tool itself) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            README (Markdown)
          </label>
          <textarea
            value={tool.readme}
            onChange={(e) =>
              setTool((prev) => ({
                ...prev,
                readme: e.target.value,
              }))
            }
            rows={10}
            placeholder="# My Tool&#10;&#10;What it does, how to use it, expected inputs/outputs..."
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Public */}
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={tool.is_public}
            onChange={(e) =>
              setTool((prev) => ({
                ...prev,
                is_public: e.target.checked,
              }))
            }
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Public tool (visible to all organizations)
        </label>
      </section>

      {/* ── Actions ───────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={saving || !tool.name || !tool.slug}
          className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? "Saving..." : mode === "edit" ? "Update Tool" : "Submit"}
        </button>
        <Link
          href={sourceId ? `/tools/${sourceId}` : "/tools"}
          className="rounded-md border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </Link>
      </div>
    </div>
  );
}
