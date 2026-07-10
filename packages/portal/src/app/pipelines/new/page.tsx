"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import {
  apiGet,
  apiPost,
  type Pipeline,
  type PipelineWithVersions,
  type Tool,
  type ToolWithVersions,
  type PaginatedResponse,
  type PipelineStepConfig,
  type PipelineEdge,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { TOOL_CATEGORIES } from "@/lib/constants";
import PipelineGraph from "@/components/pipeline-graph";
import { SchemaParamControl } from "@/components/pipeline/param-field";

const PIPELINE_TYPES = ["compute", "interactive", "hybrid"];

/* ── Helpers ────────────────────────────────────────────── */

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 255);
}

/** Derive edges from depends_on in each step. */
function deriveEdges(steps: StepFormData[]): PipelineEdge[] {
  const edges: PipelineEdge[] = [];
  for (const step of steps) {
    for (const dep of step.depends_on) {
      if (dep) edges.push({ from_step: dep, to_step: step.name });
    }
  }
  return edges;
}

/* ── Form types ─────────────────────────────────────────── */

interface StepFormData {
  name: string;
  tool_slug: string;
  tool_version: string; // "" = latest
  parameters_json: string;
  depends_on: string[];
}

function emptyStep(): StepFormData {
  return {
    name: "",
    tool_slug: "",
    tool_version: "",
    parameters_json: "{}",
    depends_on: [],
  };
}

/* ── Page ───────────────────────────────────────────────── */

export default function Page() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-500">Loading...</div>}>
      <CreatePipelinePage />
    </Suspense>
  );
}

function CreatePipelinePage() {
  const pipelinesLabel = useLabel("resource.pipeline.plural");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading } = useAuth();

  // Pipeline metadata
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugManual, setSlugManual] = useState(false);
  const [description, setDescription] = useState("");
  const [readme, setReadme] = useState("");
  const [category, setCategory] = useState("general");
  const [pipelineType, setPipelineType] = useState("compute");
  const [tags, setTags] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [parametersSchemaJson, setParametersSchemaJson] = useState("{}");
  const [defaultParametersJson, setDefaultParametersJson] = useState("{}");

  // Steps
  const [steps, setSteps] = useState<StepFormData[]>([emptyStep()]);

  // Edit mode = "new version": the shape (steps/edges/parameters_schema) is
  // locked; only per-step bindings (tool_version + parameters) and a
  // changelog are editable. Topology changes go through fork, not a new version.
  const [editId, setEditId] = useState<string | null>(null);
  const [changelog, setChangelog] = useState("");
  const locked = !!editId;

  // Tools for dropdown
  const [tools, setTools] = useState<Tool[]>([]);
  // Cache: tool id → versions (fetched on tool selection). parameters_schema is
  // kept so the step editor can render typed param fields + projection (PR2).
  const [toolVersions, setToolVersions] = useState<
    Record<
      string,
      { version: number; status: string; parameters_schema: Record<string, unknown> }[]
    >
  >({});

  // Submission
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-slug from name
  useEffect(() => {
    if (!slugManual) setSlug(slugify(name));
  }, [name, slugManual]);

  // Fetch container + pypi tools and filter to those with at least one active version.
  // (`module` is not a supported tool_type; pypi wheels are the delivery path.)
  useEffect(() => {
    if (authLoading || !user) return;
    apiGet<PaginatedResponse<Tool>>("/api/v1/tools", {
      skip: "0",
      limit: "200",
    })
      .then(async (data) => {
        const filtered = data.items.filter((t) =>
          ["container", "pypi"].includes(t.tool_type)
        );
        // Fetch versions for each tool to check for active status
        const withActive: Tool[] = [];
        await Promise.all(
          filtered.map(async (t) => {
            try {
              const toolData = await apiGet<ToolWithVersions>(`/api/v1/tools/${t.id}`);
              if (toolData.versions.some((v) => v.status === "active")) {
                withActive.push(t);
              }
            } catch {
              // ignore
            }
          })
        );
        setTools(withActive);
      })
      .catch(() => setTools([]));
  }, [user, authLoading]);

  // Prefill from existing pipeline (duplicate or edit)
  useEffect(() => {
    const fromId = searchParams.get("from");
    const editParam = searchParams.get("edit");
    const sourceId = fromId || editParam;
    if (!sourceId || authLoading || !user) return;

    apiGet<PipelineWithVersions>(`/api/v1/pipelines/${sourceId}`)
      .then((p) => {
        if (editParam) {
          // Edit mode: keep original name/slug
          setEditId(editParam);
          setName(p.name);
          setSlug(p.slug);
          setSlugManual(true);
        } else {
          // Duplicate mode: append "(copy)"
          setName(`${p.name} (copy)`);
          setSlug(slugify(`${p.name}-copy`));
        }
        setDescription(p.description ?? "");
        setReadme(p.readme ?? "");
        setCategory(p.category ?? "general");
        setPipelineType(p.pipeline_type ?? "compute");
        setTags(p.tags.join(", "));
        setIsPublic(p.is_public);

        // Load DAG from latest version
        const sorted = [...(p.versions || [])].sort((a, b) => b.version - a.version);
        const latestVersion = sorted[0];
        if (latestVersion) {
          setParametersSchemaJson(
            Object.keys(latestVersion.parameters_schema).length > 0
              ? JSON.stringify(latestVersion.parameters_schema, null, 2)
              : "{}",
          );
          // Run-input defaults are carried on parameters_schema
          // properties (loaded above), not a separate default_parameters blob.
          setDefaultParametersJson("{}");
          const srcSteps = latestVersion.steps as unknown as PipelineStepConfig[];
          if (srcSteps.length > 0) {
            setSteps(
              srcSteps.map((s) => ({
                name: s.name,
                tool_slug: s.tool_slug,
                tool_version: s.tool_version != null ? String(s.tool_version) : "",
                parameters_json:
                  Object.keys(s.parameters).length > 0
                    ? JSON.stringify(s.parameters, null, 2)
                    : "{}",
                depends_on: s.depends_on ?? [],
              })),
            );
          }
        }
      })
      .catch(() => {
        // Source pipeline not found — proceed with empty form
      });
  }, [searchParams, user, authLoading]);

  /* ── Step manipulation ──────────────────────────────── */

  const updateStep = useCallback(
    (idx: number, patch: Partial<StepFormData>) => {
      setSteps((prev) =>
        prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)),
      );
    },
    [],
  );

  // Fetch versions for a tool (cached), auto-select latest active version
  const fetchVersions = useCallback(
    (toolId: string, stepIdx?: number) => {
      if (!toolId || toolVersions[toolId]) {
        // Even if cached, auto-select latest active
        if (stepIdx !== undefined) {
          const versions = toolVersions[toolId] ?? [];
          const latestActive = versions
            .filter((v) => v.status === "active")
            .sort((a, b) => b.version - a.version)[0];
          if (latestActive) {
            updateStep(stepIdx, { tool_version: String(latestActive.version) });
          }
        }
        return;
      }
      apiGet<ToolWithVersions>(`/api/v1/tools/${toolId}`)
        .then((data) => {
          const versions = data.versions.map((v) => ({
            version: v.version,
            status: v.status,
            parameters_schema: v.parameters_schema ?? {},
          }));
          setToolVersions((prev) => ({
            ...prev,
            [toolId]: versions,
          }));
          // Auto-select latest active version
          if (stepIdx !== undefined) {
            const latestActive = versions
              .filter((v) => v.status === "active")
              .sort((a, b) => b.version - a.version)[0];
            if (latestActive) {
              updateStep(stepIdx, { tool_version: String(latestActive.version) });
            }
          }
        })
        .catch(() => {});
    },
    [toolVersions, updateStep],
  );

  const removeStep = useCallback((idx: number) => {
    setSteps((prev) => {
      const removed = prev[idx];
      // Remove any depends_on references to the removed step
      return prev
        .filter((_, i) => i !== idx)
        .map((s) => ({
          ...s,
          depends_on: s.depends_on.filter((d) => d !== removed.name),
        }));
    });
  }, []);

  const addStep = useCallback(() => {
    setSteps((prev) => [...prev, emptyStep()]);
  }, []);

  const moveStep = useCallback((idx: number, dir: -1 | 1) => {
    setSteps((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  }, []);

  // Ensure versions are loaded for every referenced tool (so the version
  // dropdown is populated — including locked/pinned steps in edit mode), and
  // auto-select latest active only for steps that don't have a pin yet.
  useEffect(() => {
    let changed = false;
    const newSteps = steps.map((step, i) => {
      if (!step.tool_slug) return step;
      const tool = tools.find((t) => t.slug === step.tool_slug);
      if (!tool) return step;
      const versions = toolVersions[tool.id];
      if (!versions) {
        // Only auto-select when the step has no pin yet.
        fetchVersions(tool.id, step.tool_version ? undefined : i);
        return step;
      }
      if (step.tool_version) return step;
      const latestActive = versions
        .filter((v) => v.status === "active")
        .sort((a, b) => b.version - a.version)[0];
      if (!latestActive) return step;
      changed = true;
      return { ...step, tool_version: String(latestActive.version) };
    });
    if (changed) {
      setSteps(newSteps);
    }
  }, [steps, tools, toolVersions, fetchVersions]);

  /* ── Step parameter projection (schema-driven) ──────── */

  // Resolve the pinned tool-version's parameter properties for a step. The
  // binding's keys select which of these to expose; values are their defaults.
  const stepSchemaProps = useCallback(
    (step: StepFormData): Record<string, Record<string, unknown>> => {
      const tool = tools.find((t) => t.slug === step.tool_slug);
      if (!tool) return {};
      const vers = toolVersions[tool.id] ?? [];
      const v = step.tool_version
        ? vers.find((x) => String(x.version) === step.tool_version)
        : vers.filter((x) => x.status === "active").sort((a, b) => b.version - a.version)[0];
      return ((v?.parameters_schema as Record<string, unknown>)?.properties ?? {}) as Record<
        string,
        Record<string, unknown>
      >;
    },
    [tools, toolVersions],
  );

  const parseStepParams = (step: StepFormData): Record<string, unknown> => {
    try {
      const v = JSON.parse(step.parameters_json || "{}");
      return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  };

  // Write a single param key into a step's parameters_json (value === undefined
  // removes the key — i.e. "not exposed").
  const setStepParam = useCallback(
    (idx: number, key: string, value: unknown) => {
      setSteps((prev) =>
        prev.map((s, i) => {
          if (i !== idx) return s;
          let parsed: Record<string, unknown> = {};
          try {
            const v = JSON.parse(s.parameters_json || "{}");
            if (v && typeof v === "object") parsed = v as Record<string, unknown>;
          } catch {
            parsed = {};
          }
          if (value === undefined) delete parsed[key];
          else parsed[key] = value;
          return { ...s, parameters_json: JSON.stringify(parsed, null, 2) };
        }),
      );
    },
    [],
  );

  /* ── Graph preview data ─────────────────────────────── */

  const previewSteps: PipelineStepConfig[] = useMemo(
    () =>
      steps
        .filter((s) => s.name.trim())
        .map((s) => ({
          name: s.name.trim(),
          tool_slug: s.tool_slug || "unset",
          tool_version: s.tool_version ? Number(s.tool_version) : null,
          parameters: {},
          depends_on: s.depends_on.filter(Boolean),
        })),
    [steps],
  );

  /* ── Validation ─────────────────────────────────────── */

  const stepNames = useMemo(
    () => steps.map((s) => s.name.trim()).filter(Boolean),
    [steps],
  );

  const duplicateNames = useMemo(() => {
    const seen = new Set<string>();
    const dupes = new Set<string>();
    for (const n of stepNames) {
      if (seen.has(n)) dupes.add(n);
      seen.add(n);
    }
    return dupes;
  }, [stepNames]);

  // Pipeline type is determined by the kinds of tools in the DAG:
  //   compute     → every tool is pypi or container
  //   interactive → every tool is human
  //   hybrid      → any other mix
  const stepToolTypes = useMemo(() => {
    const types = new Set<string>();
    for (const s of steps) {
      if (!s.tool_slug) continue;
      const t = tools.find((x) => x.slug === s.tool_slug);
      if (t) types.add(t.tool_type);
    }
    return types;
  }, [steps, tools]);

  const impliedType = useMemo<string | null>(() => {
    if (stepToolTypes.size === 0) return null;
    const arr = [...stepToolTypes];
    if (arr.every((t) => t === "pypi" || t === "container")) return "compute";
    if (arr.every((t) => t === "human")) return "interactive";
    return "hybrid";
  }, [stepToolTypes]);

  const typeMismatch = impliedType != null && impliedType !== pipelineType;

  /* ── Submit ─────────────────────────────────────────── */

  const handleSubmit = async () => {
    setError(null);

    // Basic validation
    if (!name.trim()) {
      setError("Pipeline name is required.");
      return;
    }
    if (!slug.trim()) {
      setError("Pipeline slug is required.");
      return;
    }
    if (steps.length === 0 || !steps[0].name.trim()) {
      setError("At least one step with a name is required.");
      return;
    }
    if (duplicateNames.size > 0) {
      setError(`Duplicate step names: ${[...duplicateNames].join(", ")}`);
      return;
    }
    for (const s of steps) {
      if (!s.name.trim()) {
        setError("All steps must have a name.");
        return;
      }
      if (!s.tool_slug) {
        setError(`Step "${s.name}" must have a tool selected.`);
        return;
      }
      if (!s.tool_version) {
        setError(`Step "${s.name}" must have a tool version selected.`);
        return;
      }
    }

    // Pipeline type must match the kinds of tools in the DAG (create only).
    if (!locked && typeMismatch && impliedType) {
      setError(
        `Pipeline type "${pipelineType}" does not match the selected tools ` +
          `(${[...stepToolTypes].join(", ")}). Set the type to "${impliedType}".`,
      );
      return;
    }

    // Parse JSON fields
    let parametersSchema: Record<string, unknown> = {};
    let defaultParameters: Record<string, unknown> = {};
    try {
      parametersSchema = JSON.parse(parametersSchemaJson);
    } catch {
      setError("Parameters schema is not valid JSON.");
      return;
    }
    try {
      defaultParameters = JSON.parse(defaultParametersJson);
    } catch {
      setError("Default parameters is not valid JSON.");
      return;
    }

    const builtSteps: PipelineStepConfig[] = [];
    for (const s of steps) {
      let params: Record<string, unknown> = {};
      try {
        params = JSON.parse(s.parameters_json);
      } catch {
        setError(`Step "${s.name}" has invalid parameters JSON.`);
        return;
      }
      const tool = tools.find((t) => t.slug === s.tool_slug);
      builtSteps.push({
        name: s.name.trim(),
        tool_slug: s.tool_slug,
        tool_version: s.tool_version ? Number(s.tool_version) : null,
        tool_type: tool?.tool_type || "container",
        parameters: params,
        depends_on: s.depends_on.filter(Boolean),
      });
    }

    const edges = deriveEdges(steps);
    const tagList = tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    setSubmitting(true);
    try {
      let pipeline: Pipeline;
      if (editId) {
        // A new version is a *binding* over the locked shape — it
        // pins tool versions and parameters, nothing structural. Metadata is
        // edited separately (the Update Pipeline Definition modal); topology
        // changes require a fork.
        const bindings: Record<
          string,
          { tool_version: number | null; parameters: Record<string, unknown> }
        > = {};
        for (const bs of builtSteps) {
          bindings[bs.name] = { tool_version: bs.tool_version ?? null, parameters: bs.parameters };
        }
        await apiPost(`/api/v1/pipelines/${editId}/versions`, {
          bindings,
          changelog: changelog.trim() || null,
        });
        pipeline = { id: editId } as Pipeline;
      } else {
        // Create new pipeline (includes initial version)
        pipeline = await apiPost<Pipeline>("/api/v1/pipelines", {
          name: name.trim(),
          slug: slug.trim(),
          description: description.trim() || null,
          readme: readme.trim() || null,
          category,
          pipeline_type: pipelineType,
          steps: builtSteps,
          edges,
          parameters_schema: parametersSchema,
          default_parameters: defaultParameters,
          tags: tagList,
          is_public: isPublic,
        });
      }
      router.push(`/pipelines/${pipeline.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : editId ? "Failed to update pipeline" : "Failed to create pipeline");
    } finally {
      setSubmitting(false);
    }
  };

  /* ── Auth guards ────────────────────────────────────── */

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please <a href="/login" className="text-blue-600 underline">log in</a> to create pipelines.
      </p>
    );

  /* ── Render ─────────────────────────────────────────── */

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/pipelines" className="hover:text-blue-600">
          {pipelinesLabel}
        </Link>
        <span>/</span>
        <span>{editId ? "New version" : "New"}</span>
      </div>

      <h1 className="text-2xl font-bold text-gray-900">
        {editId ? "New Version" : "Create Pipeline"}
      </h1>

      {locked ? (
        /* ── Locked context (edit = new version) ───────── */
        <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-2">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-gray-700">Pipeline</label>
              <p className="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{name}</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Slug</label>
              <p className="mt-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 font-mono text-sm text-gray-600">{slug}</p>
            </div>
          </div>
          <p className="text-xs text-gray-500">
            A new version pins tool versions and parameters over the pipeline&apos;s
            <span className="font-medium"> locked DAG</span>. The topology can&apos;t change
            here — fork the pipeline to evolve its structure. Metadata is edited from the
            pipeline page.
          </p>
        </section>
      ) : (
      /* ── Pipeline metadata ──────────────────────────── */
      <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
        <h2 className="text-lg font-semibold text-gray-900">Details</h2>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My docking pipeline"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* Slug */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Slug <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setSlugManual(true);
              }}
              disabled={!!editId}
              placeholder="my-docking-pipeline"
              className={`w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 ${editId ? "bg-gray-100 text-gray-500" : ""}`}
            />
            <p className="mt-1 text-xs text-gray-400">
              {editId ? "Slug cannot be changed." : "Lowercase, hyphens, dots, underscores. Auto-generated from name."}
            </p>
          </div>
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Optional description of this pipeline..."
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Category */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {TOOL_CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Type
            </label>
            <select
              value={pipelineType}
              onChange={(e) => setPipelineType(e.target.value)}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {PIPELINE_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>

        {/* README */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            README
            <span className="ml-2 text-xs font-normal text-gray-400">Markdown · optional</span>
          </label>
          <textarea
            value={readme}
            onChange={(e) => setReadme(e.target.value)}
            rows={6}
            placeholder="Document what this pipeline does, its inputs/outputs, and how to use it…"
            className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* Tags */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tags
            </label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="docking, virtual-screening"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">Comma-separated</p>
          </div>

          {/* Public */}
          <div className="flex items-center gap-2 pt-6">
            <input
              id="is_public"
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <label htmlFor="is_public" className="text-sm text-gray-700">
              Public pipeline
            </label>
          </div>
        </div>
      </section>
      )}

      {/* ── Type ↔ tools validation ────────────────────── */}
      {!locked && (
        <section
          className={`rounded-lg border p-4 text-sm ${
            impliedType == null
              ? "border-gray-200 bg-gray-50 text-gray-500"
              : typeMismatch
                ? "border-amber-300 bg-amber-50 text-amber-800"
                : "border-green-200 bg-green-50 text-green-800"
          }`}
        >
          <div className="flex items-start gap-2">
            <span className="mt-0.5">
              {impliedType == null ? "—" : typeMismatch ? "⚠️" : "✓"}
            </span>
            <div className="space-y-1">
              {impliedType == null ? (
                <p>Select a tool for each step to validate the pipeline type.</p>
              ) : typeMismatch ? (
                <>
                  <p>
                    The selected tools ({[...stepToolTypes].join(", ")}) require type{" "}
                    <span className="font-semibold">{impliedType}</span>, but{" "}
                    <span className="font-semibold">{pipelineType}</span> is selected.
                  </p>
                  <button
                    type="button"
                    onClick={() => setPipelineType(impliedType)}
                    className="rounded-md border border-amber-400 bg-white px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
                  >
                    Set type to “{impliedType}”
                  </button>
                </>
              ) : (
                <p>
                  Type <span className="font-semibold">{pipelineType}</span> matches the
                  selected tools ({[...stepToolTypes].join(", ")}).
                </p>
              )}
              <p className="text-xs opacity-80">
                compute = all pypi/container · interactive = all human · hybrid = any other mix
              </p>
            </div>
          </div>
        </section>
      )}

      {/* ── Steps ──────────────────────────────────────── */}
      <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">
            {locked ? "Step bindings" : `Steps (${steps.length})`}
          </h2>
          {!locked && (
            <button
              type="button"
              onClick={addStep}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              + Add Step
            </button>
          )}
        </div>
        {locked && (
          <p className="text-xs text-gray-500">
            The step graph is fixed by the pipeline&apos;s shape. For each step, choose the
            tool version to pin and the parameter values to use.
          </p>
        )}

        <div className="space-y-4">
          {steps.map((step, idx) => (
            <div
              key={idx}
              className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-700">
                  Step {idx + 1}
                </span>
                {!locked && (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => moveStep(idx, -1)}
                      disabled={idx === 0}
                      className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-200 disabled:opacity-30"
                      title="Move up"
                    >
                      &uarr;
                    </button>
                    <button
                      type="button"
                      onClick={() => moveStep(idx, 1)}
                      disabled={idx === steps.length - 1}
                      className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-200 disabled:opacity-30"
                      title="Move down"
                    >
                      &darr;
                    </button>
                    <button
                      type="button"
                      onClick={() => removeStep(idx)}
                      disabled={steps.length === 1}
                      className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-30"
                    >
                      Remove
                    </button>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {/* Step name */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={step.name}
                    onChange={(e) => updateStep(idx, { name: e.target.value })}
                    readOnly={locked}
                    placeholder="prep-ligands"
                    className={`w-full rounded-md border px-3 py-1.5 text-sm ${
                      locked
                        ? "border-gray-200 bg-gray-100 text-gray-500"
                        : step.name && duplicateNames.has(step.name)
                          ? "border-red-400 bg-red-50"
                          : "border-gray-300"
                    } focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
                  />
                  {!locked && step.name && duplicateNames.has(step.name) && (
                    <p className="mt-0.5 text-xs text-red-500">Duplicate name</p>
                  )}
                </div>

                {/* Tool */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Tool <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={step.tool_slug}
                    disabled={locked}
                    onChange={(e) => {
                      const slug = e.target.value;
                      const tool = tools.find((t) => t.slug === slug);
                      if (tool) fetchVersions(tool.id, idx);
                      updateStep(idx, { tool_slug: slug });
                    }}
                    className={`w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 ${locked ? "bg-gray-100 text-gray-500" : ""}`}
                  >
                    <option value="">Select a tool...</option>
                    {tools.map((t) => (
                      <option key={t.slug} value={t.slug}>
                        {t.name} ({t.slug}) [{t.tool_type}]
                      </option>
                    ))}
                  </select>
                </div>

                {/* Tool version */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Version <span className="text-red-500">*</span>
                  </label>
                   <select
                     value={step.tool_version}
                     onChange={(e) =>
                       updateStep(idx, { tool_version: e.target.value })
                     }
                     className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                   >
                     <option value="">Select a version...</option>
                     {(() => {
                       const tool = tools.find((t) => t.slug === step.tool_slug);
                       const versions = tool ? toolVersions[tool.id] ?? [] : [];
                       return versions
                         .filter((v) => v.status === "active")
                         .map((v) => (
                           <option key={v.version} value={String(v.version)}>
                             v{v.version}
                           </option>
                         ));
                     })()}
                   </select>
                </div>
              </div>

              {/* Depends on */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Depends on
                </label>
                <div className="flex flex-wrap gap-2">
                  {locked
                    ? (step.depends_on.length > 0
                        ? step.depends_on.map((n) => (
                            <span
                              key={n}
                              className="rounded-full border border-gray-300 bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600"
                            >
                              {n}
                            </span>
                          ))
                        : <span className="text-xs text-gray-400">No dependencies</span>)
                    : stepNames
                        .filter((n) => n !== step.name)
                        .map((n) => {
                          const selected = step.depends_on.includes(n);
                          return (
                            <button
                              key={n}
                              type="button"
                              onClick={() => {
                                const next = selected
                                  ? step.depends_on.filter((d) => d !== n)
                                  : [...step.depends_on, n];
                                updateStep(idx, { depends_on: next });
                              }}
                              className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors ${
                                selected
                                  ? "border-blue-400 bg-blue-100 text-blue-700"
                                  : "border-gray-300 bg-white text-gray-600 hover:bg-gray-100"
                              }`}
                            >
                              {n}
                            </button>
                          );
                        })}
                  {!locked && stepNames.filter((n) => n !== step.name).length === 0 && (
                    <span className="text-xs text-gray-400">
                      No other named steps to depend on
                    </span>
                  )}
                </div>
              </div>

              {/* Parameters — schema-driven projection (PR2). Each tool-version
                  parameter has an "expose" toggle; exposed keys become the
                  binding (value = default; empty = exposed with no default). */}
              {(() => {
                const props = stepSchemaProps(step);
                const parsed = parseStepParams(step);
                const propKeys = Object.keys(props);
                if (propKeys.length === 0) {
                  // No schema yet (tool/version not selected or has no params) —
                  // fall back to raw JSON so nothing is lost.
                  return (
                    <details className="group">
                      <summary className="cursor-pointer text-xs font-medium text-gray-500 hover:text-gray-700">
                        Step parameters (JSON)
                      </summary>
                      <textarea
                        value={step.parameters_json}
                        onChange={(e) => updateStep(idx, { parameters_json: e.target.value })}
                        rows={3}
                        className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </details>
                  );
                }
                return (
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-xs font-medium text-gray-600">Parameters</span>
                      <span className="text-[10px] text-gray-400">
                        check to expose in the run form
                      </span>
                    </div>
                    <div className="divide-y divide-gray-100 rounded-md border border-gray-200 bg-white">
                      {propKeys.map((key) => {
                        const def = props[key] ?? {};
                        const exposed = key in parsed;
                        return (
                          <div key={key} className="flex items-start gap-2 px-3 py-2">
                            <input
                              type="checkbox"
                              checked={exposed}
                              onChange={() =>
                                exposed
                                  ? setStepParam(idx, key, undefined)
                                  : setStepParam(idx, key, def.default ?? null)
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
                                <p className="text-[11px] text-gray-400">{String(def.description)}</p>
                              )}
                              {exposed && (
                                <div className="mt-1">
                                  <SchemaParamControl
                                    propDef={def}
                                    value={parsed[key]}
                                    onChange={(v) => setStepParam(idx, key, v)}
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
                    <details className="group mt-1">
                      <summary className="cursor-pointer text-[11px] text-gray-400 hover:text-gray-600">
                        Edit as JSON
                      </summary>
                      <textarea
                        value={step.parameters_json}
                        onChange={(e) => updateStep(idx, { parameters_json: e.target.value })}
                        rows={3}
                        className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </details>
                  </div>
                );
              })()}
            </div>
          ))}
        </div>
      </section>

      {/* ── Graph preview ──────────────────────────────── */}
      {previewSteps.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-3">
          <h2 className="text-lg font-semibold text-gray-900">Graph Preview</h2>
          <PipelineGraph steps={previewSteps} height="280px" />
        </section>
      )}

      {/* ── Advanced: parameters schema (shape — create only) ── */}
      {!locked && (
        <details className="rounded-lg border border-gray-200 bg-white">
          <summary className="cursor-pointer p-5 text-sm font-semibold text-gray-700 hover:text-gray-900">
            Advanced: Pipeline Parameters Schema
          </summary>
          <div className="space-y-4 px-5 pb-5">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Parameters Schema (JSON Schema)
              </label>
              <textarea
                value={parametersSchemaJson}
                onChange={(e) => setParametersSchemaJson(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Default Parameters (JSON)
              </label>
              <textarea
                value={defaultParametersJson}
                onChange={(e) => setDefaultParametersJson(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        </details>
      )}

      {/* ── Changelog (new version only) ───────────────── */}
      {locked && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
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
        </section>
      )}

      {/* ── Error + submit ─────────────────────────────── */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
           {submitting
              ? editId ? "Creating version..." : "Creating..."
              : editId ? "Create Version" : "Create Pipeline"}
        </button>
        <Link
          href="/pipelines"
          className="rounded-md border border-gray-300 px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </Link>
      </div>
    </div>
  );
}
