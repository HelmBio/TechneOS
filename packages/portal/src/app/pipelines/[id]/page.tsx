"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import {
  apiGet,
  apiPost,
  apiPatch,
  API_BASE,
  getToken,
  type PipelineWithVersions,
  type PipelineVersion,
  type PipelineStepConfig,
  type PipelineRun,
  type PipelineRunDetail,
  type PaginatedResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/rbac";
import { useSubscriptions } from "@/lib/use-subscriptions";
import DatasetSelector from "@/components/dataset-selector";
import { DetailHeader } from "@/components/tool/detail-header";
import { DetailMetadata } from "@/components/tool/detail-metadata";
import { DetailReadme } from "@/components/tool/detail-readme";
import { DetailRunHistoryHeader } from "@/components/tool/detail-run-history-header";
import { PipelineVersionCard } from "@/components/pipeline/version-card";
import PipelineGraph from "@/components/pipeline-graph";
import { SchemaParamControl, isEmptyParam } from "@/components/pipeline/param-field";
import { PipelineVersionEditorModal } from "@/components/pipeline/version-editor-modal";
import { PipelineMetadataModal } from "@/components/pipeline/metadata-modal";
import { StatusBadge } from "@/components/run/status-badge";
import { formatDuration } from "@/lib/run-utils";

// ── Input-data handling ─────────────────────────────────────────────────
// Pipeline inputs flagged with `x-input` in the parameters_schema are real
// tool input data (a SMILES list, a receptor PDB, …) and get the same
// Dataset / Upload / Paste choices as the tool-run form. Each input is
// assigned to a step via `x-step`; on submit it is staged via the
// pipeline-run staging endpoints and passed in the run's `inputs` array.
// The service relocates it to the run's `inputs/` prefix, records the
// input artifact (io_type='input'), and injects the namespaced typed
// pointer (`<step>.<field>`) into the run parameters for the worker.

type InputMode = "dataset" | "upload" | "inline";

interface InputFieldState {
  mode: InputMode;
  value: string; // dataset ref (dataset mode) or pasted text (inline mode)
  file: File | null;
}

// Matches the backend PipelineRunInputStage — passed back verbatim in the
// run's `inputs` array so the service relocates the file and creates the
// input artifact (io_type='input').
interface StagedRef {
  id: string;
  parameter_name: string;
  file_name: string;
  file_size: number;
  content_type: string;
  storage_bucket: string;
  storage_key: string;
  source: string;
  checksum_sha256: string;
}

const isInputProp = (propDef: Record<string, unknown> | undefined): boolean =>
  propDef?.["x-input"] === true || propDef?.format === "dataset";

const stepOfProp = (propDef: Record<string, unknown> | undefined): string | null =>
  (propDef?.["x-step"] as string | undefined) ?? null;

function detectPasteContentType(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    try {
      JSON.parse(trimmed);
      return "application/json";
    } catch {
      // fall through
    }
  }
  const firstLine = trimmed.split(/\r?\n/, 1)[0] ?? "";
  if (firstLine.includes("\t")) return "text/tab-separated-values";
  if (firstLine.includes(",")) return "text/csv";
  return "text/plain";
}

async function stageUpload(
  file: File,
  parameterName: string,
  pipelineSlug: string,
  pipelineVersion: number,
): Promise<StagedRef> {
  const form = new FormData();
  form.append("file", file);
  form.append("parameter_name", parameterName);
  form.append("pipeline_slug", pipelineSlug);
  form.append("pipeline_version", String(pipelineVersion));
  const token = getToken();
  const resp = await fetch(`${API_BASE}/api/v1/pipeline-runs/inputs`, {
    method: "POST",
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}) as Record<string, unknown>);
    throw new Error(`Upload failed for ${file.name}: ${(body as { detail?: string }).detail || resp.status}`);
  }
  return (await resp.json()) as StagedRef;
}

async function stagePaste(
  content: string,
  parameterName: string,
  contentType: string,
  pipelineSlug: string,
  pipelineVersion: number,
): Promise<StagedRef> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}/api/v1/pipeline-runs/inputs/paste`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      parameter_name: parameterName,
      content,
      content_type: contentType,
      pipeline_slug: pipelineSlug,
      pipeline_version: pipelineVersion,
    }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}) as Record<string, unknown>);
    throw new Error(`Paste staging failed: ${(body as { detail?: string }).detail || resp.status}`);
  }
  return (await resp.json()) as StagedRef;
}

// Dataset / Upload / Paste widget — mirrors the tool-run form's DataField.
function InputDataField({
  name,
  description,
  required,
  state,
  onChange,
}: {
  name: string;
  description?: string;
  required?: boolean;
  state: InputFieldState;
  onChange: (patch: Partial<InputFieldState>) => void;
}) {
  const tabs: { mode: InputMode; label: string }[] = [
    { mode: "dataset", label: "Dataset" },
    { mode: "upload", label: "Upload" },
    { mode: "inline", label: "Paste" },
  ];
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700">
        {name}
        {required && <span className="text-red-500 ml-0.5">*</span>}
        {description && (
          <span className="ml-2 text-xs font-normal text-gray-500">— {description}</span>
        )}
      </label>
      <div className="mt-1 inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5 text-xs">
        {tabs.map((t) => (
          <button
            key={t.mode}
            type="button"
            onClick={() => onChange({ mode: t.mode, value: "", file: null })}
            className={`px-2.5 py-1 rounded ${
              state.mode === t.mode
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="mt-2">
        {state.mode === "dataset" && (
          <DatasetSelector value={state.value} onChange={(v) => onChange({ value: v })} />
        )}
        {state.mode === "upload" && (
          <input
            type="file"
            onChange={(e) => onChange({ file: e.target.files?.[0] ?? null })}
            className="block w-full text-sm text-gray-700 file:mr-3 file:rounded file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-blue-700 hover:file:bg-blue-100"
          />
        )}
        {state.mode === "inline" && (
          <textarea
            value={state.value}
            onChange={(e) => onChange({ value: e.target.value })}
            placeholder={
              'One SMILES per line, or ["CCO","c1ccccc1"], or a CSV with a smiles column.\n' +
              "The platform parses the content the same way as an uploaded file."
            }
            rows={4}
            className="block w-full rounded border border-gray-300 bg-white px-3 py-2 font-mono text-xs"
          />
        )}
      </div>
    </div>
  );
}


// Seed the run form's param values from a version's parameters_schema defaults
// and its per-step parameter overrides (step params are namespaced "step.key").
function computeVersionDefaults(version: PipelineVersion): Record<string, unknown> {
  const schema = (version.parameters_schema ?? {}) as Record<string, unknown>;
  const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const defaults: Record<string, unknown> = {};
  for (const [k, propDef] of Object.entries(props)) {
    // Input-data fields are handled by the Dataset/Upload/Paste widget, not paramValues.
    if (isInputProp(propDef)) continue;
    // Run-input defaults live on the schema property itself. Values are
    // kept typed (number/boolean/array/string) — the widgets and submit are typed.
    if (propDef?.default !== undefined) defaults[k] = propDef.default;
  }
  const steps = (version.steps ?? []) as Record<string, unknown>[];
  for (const s of steps) {
    const stepName = (s.name as string) || "";
    const stepParams = (s.parameters as Record<string, unknown>) ?? {};
    // The pinned tool-version's schema (attached server-side) supplies fallback
    // defaults when a binding value is null ("exposed, no author default").
    const stepProps = ((s.parameters_schema as Record<string, unknown>)?.properties ??
      {}) as Record<string, Record<string, unknown>>;
    for (const [k, v] of Object.entries(stepParams)) {
      const nsKey = `${stepName}.${k}`;
      const effective = v != null && v !== "" ? v : (stepProps[k]?.default ?? null);
      if (!isEmptyParam(effective)) defaults[nsKey] = effective;
    }
  }
  return defaults;
}

// Initial Dataset/Upload/Paste state for each x-input field of a version.
function computeInputFieldStates(version: PipelineVersion): Record<string, InputFieldState> {
  const schema = (version.parameters_schema ?? {}) as Record<string, unknown>;
  const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const states: Record<string, InputFieldState> = {};
  for (const [k, propDef] of Object.entries(props)) {
    if (isInputProp(propDef)) {
      states[k] = { mode: "dataset", value: "", file: null };
    }
  }
  return states;
}

export default function PipelineDetailPage() {
  const pipelinesLabel = useLabel("resource.pipeline.plural");
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const sourceRunId = searchParams.get("run");
  const { user, loading: authLoading } = useAuth();
  const { isFollowed, toggle } = useSubscriptions("pipeline");
  const [pipeline, setPipeline] = useState<PipelineWithVersions | null>(null);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsOpen, setRunsOpen] = useState(true);
  const [statusUpdating, setStatusUpdating] = useState<string | null>(null);
  const [showEditModal, setShowEditModal] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showRunModal, setShowRunModal] = useState(false);
  const [showVersionModal, setShowVersionModal] = useState(false);
  const [editVersionId, setEditVersionId] = useState<string | null>(null);
  const [paramValues, setParamValues] = useState<Record<string, unknown>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [sourceRunLoaded, setSourceRunLoaded] = useState(false);
  const [runName, setRunName] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");
  // Wizard "train stop": 0 = pipeline params, 1..N = step params (step index + 1).
  const [wizardStop, setWizardStop] = useState(0);
  // Dataset/Upload/Paste state for each x-input field, keyed by field name.
  const [dataFieldStates, setDataFieldStates] = useState<Record<string, InputFieldState>>({});

  const fetchPipeline = useCallback(() => {
    if (!id) return;
    setLoading(true);
    apiGet<PipelineWithVersions>(`/api/v1/pipelines/${id}`)
      .then((data) => {
        setPipeline(data);
        // Default to the latest version
        if (data.versions && data.versions.length > 0) {
          const sorted = [...data.versions].sort((a, b) => b.version - a.version);
          const latestVersion = sorted[0];
          setSelectedVersionId(latestVersion.id);

          // Seed param form from latest version's parameters_schema and steps
          setParamValues(computeVersionDefaults(latestVersion));
          setDataFieldStates(computeInputFieldStates(latestVersion));
        }
      })
      .catch(() => setPipeline(null))
      .finally(() => setLoading(false));
  }, [id]);

  const fetchRuns = useCallback(() => {
    if (!id) return;
    apiGet<PaginatedResponse<PipelineRun>>("/api/v1/pipeline-runs", {
      pipeline_id: id,
      skip: "0",
      limit: "10",
    })
      .then((data) => { setRuns(data.items); setRunsTotal(data.total); })
      .catch(() => setRuns([]));
  }, [id]);

  useEffect(() => {
    if (authLoading || !user) return;
    fetchPipeline();
    fetchRuns();
  }, [user, authLoading, fetchPipeline, fetchRuns]);

  // Pre-fill parameters from a source run (duplicate flow via ?run=)
  useEffect(() => {
    if (!sourceRunId || !pipeline || sourceRunLoaded) return;
    apiGet<PipelineRunDetail>(`/api/v1/pipeline-runs/${sourceRunId}`)
      .then((run) => {
        // Run parameters are already typed; carry them through as-is.
        setParamValues((prev) => ({ ...prev, ...(run.parameters ?? {}) }));
        if (run.name) setRunName(run.name);
        // Input data (typed pointers) can't be reversed into UI state — reset
        // the Dataset/Upload/Paste widgets so the user re-selects inputs.
        const dv = [...(pipeline.versions || [])].sort((a, b) => b.version - a.version)[0];
        if (dv) setDataFieldStates(computeInputFieldStates(dv));
        setWizardStop(0);
        setShowRunModal(true);
        setSourceRunLoaded(true);
      })
      .catch(() => {
        setSourceRunLoaded(true);
      });
  }, [sourceRunId, pipeline, sourceRunLoaded]);

  const handleSubmitRun = async () => {
    if (!id || !pipeline) return;
    setSubmitError(null);

    const selectedVersion = (pipeline.versions || []).find((v) => v.id === selectedVersionId);
    const schema = (selectedVersion?.parameters_schema ?? {}) as Record<string, unknown> | undefined;
    const sProps = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
    const sSteps = (selectedVersion?.steps ?? []) as Record<string, unknown>[];
    const required = (schema?.required ?? []) as string[];

    // Jump to (and report) the stop that owns the first invalid required field.
    const failOnField = (key: string, message: string) => {
      const owningStep = sProps[key]?.["x-step"] as string | undefined;
      let targetStop = 0;
      if (owningStep) {
        const idx = sSteps.findIndex((st) => (st.name as string) === owningStep);
        if (idx >= 0) targetStop = idx + 1;
      }
      setWizardStop(targetStop);
      setSubmitError(message);
    };

    // Whether an x-input field has any content selected.
    const inputHasContent = (key: string): boolean => {
      const st = dataFieldStates[key];
      if (!st) return false;
      if (st.mode === "upload") return st.file != null;
      return st.value.trim() !== "";
    };

    // Validate required fields — input fields vs plain params.
    for (const key of required) {
      const isInput = isInputProp(sProps[key]);
      const ok = isInput ? inputHasContent(key) : !isEmptyParam(paramValues[key]);
      if (!ok) {
        failOnField(key, `Required ${isInput ? "input" : "parameter"} missing: ${key}`);
        return;
      }
    }

    setSubmitting(true);
    try {
      // Param values are already typed (the widgets store JSON, not strings);
      // send the non-empty ones.
      const params: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(paramValues)) {
        if (!isEmptyParam(v)) params[k] = v;
      }

      // Stage each upload/paste input under the pipeline run's scratch space
      // and collect the refs. The backend relocates them to the run's
      // inputs/ prefix, records the input artifact, and injects the typed
      // pointer under each input's owning-step namespace. Dataset refs are
      // not staged files, so they go straight into params.
      const pipelineSlug = pipeline.slug;
      const pipelineVersionNo = selectedVersion?.version ?? 1;
      const inputs: StagedRef[] = [];
      for (const [name, state] of Object.entries(dataFieldStates)) {
        const propDef = sProps[name];
        const owningStep = stepOfProp(propDef);
        const key = owningStep ? `${owningStep}.${name}` : name;

        if (state.mode === "dataset") {
          if (state.value.trim()) params[key] = { type: "dataset", ref: state.value.trim() };
        } else if (state.mode === "upload") {
          if (!state.file) continue;
          inputs.push(await stageUpload(state.file, name, pipelineSlug, pipelineVersionNo));
        } else if (state.mode === "inline") {
          if (!state.value.trim()) continue;
          const contentType = detectPasteContentType(state.value);
          inputs.push(await stagePaste(state.value, name, contentType, pipelineSlug, pipelineVersionNo));
        }
      }

      const run = await apiPost<PipelineRun>("/api/v1/pipeline-runs", {
        pipeline_id: id,
        version_id: selectedVersionId || undefined,
        parameters: params,
        inputs,
        name: runName.trim() || undefined,
      });
      router.push(`/pipeline-runs/${run.id}`);
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : "Failed to submit run");
    } finally {
      setSubmitting(false);
    }
  };

  // Update a version's lifecycle status (draft/testing/active/deprecated).
  const handleVersionStatusChange = async (versionId: string, status: string) => {
    if (!pipeline) return;
    setStatusUpdating(versionId);
    try {
      await apiPatch<PipelineVersion>(
        `/api/v1/pipelines/${pipeline.id}/versions/${versionId}`,
        { status },
      );
      fetchPipeline();
    } catch {
      // ignore
    } finally {
      setStatusUpdating(null);
    }
  };

  // Open the run modal for a specific version (triggered from the version header).
  const openRunForVersion = (versionId: string) => {
    const v = (pipeline?.versions || []).find((x) => x.id === versionId);
    setSelectedVersionId(versionId);
    if (v) {
      setParamValues(computeVersionDefaults(v));
      setDataFieldStates(computeInputFieldStates(v));
    }
    setSubmitError(null);
    setWizardStop(0);
    setShowRunModal(true);
  };

  // Single parameter field, shared by the pipeline stop and each step stop.
  // Non-dataset params render via the shared SchemaParamControl (boolean / enum /
  // array-enum / typed text), driven by the schema property `propDef`.
  const renderParamField = (opts: {
    fieldKey: string;
    label: string;
    description?: string;
    required?: boolean;
    typeHint?: string;
    isDataset: boolean;
    placeholder?: string;
    propDef?: Record<string, unknown>;
  }) => (
    <div key={opts.fieldKey}>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {opts.label}
        {opts.required && <span className="text-red-500 ml-0.5">*</span>}
        {opts.typeHint && (
          <span className="ml-2 text-xs font-normal text-gray-400">({opts.typeHint})</span>
        )}
      </label>
      {opts.description && <p className="text-xs text-gray-400 mb-1">{opts.description}</p>}
      {opts.isDataset ? (
        <DatasetSelector
          value={String(paramValues[opts.fieldKey] ?? "")}
          onChange={(v) => setParamValues((prev) => ({ ...prev, [opts.fieldKey]: v }))}
        />
      ) : (
        <SchemaParamControl
          propDef={opts.propDef ?? {}}
          value={paramValues[opts.fieldKey]}
          onChange={(v) => setParamValues((prev) => ({ ...prev, [opts.fieldKey]: v }))}
          placeholder={opts.placeholder ?? (opts.required ? "required" : "optional")}
        />
      )}
    </div>
  );

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please <a href="/login" className="text-blue-600 underline">log in</a> to view pipelines.
      </p>
    );
  if (loading) return <p className="p-8 text-gray-500">Loading pipeline...</p>;
  if (!pipeline) return <p className="p-8 text-red-500">Pipeline not found.</p>;

  const sortedVersions = [...(pipeline.versions || [])].sort((a, b) => b.version - a.version);

  // Declared run inputs (x-input properties) — the identity-relevant part of the
  // run-I/O contract, part of the locked shape. Same view as the
  // Update Pipeline Definition modal.
  const pipelineSchema = (pipeline.parameters_schema ?? {}) as Record<string, unknown>;
  const pipelineRequired = Array.isArray(pipelineSchema.required)
    ? (pipelineSchema.required as string[])
    : [];
  const pipelineProps = (pipelineSchema.properties ?? {}) as Record<string, Record<string, unknown>>;
  const pipelineRunInputs = Object.entries(pipelineProps)
    .filter(([, spec]) => isInputProp(spec))
    .map(([nm, spec]) => ({
      name: nm,
      type: typeof spec.type === "string" ? (spec.type as string) : undefined,
      step: stepOfProp(spec),
      required: pipelineRequired.includes(nm),
    }));

  const permissions = user?.permissions || [];
  const canUpdate =
    (hasPermission(permissions, "pipeline", "update", "org") ||
      (hasPermission(permissions, "pipeline", "update", "own") && pipeline.created_by === user.id)) &&
    (pipeline.org_id === user.org_id || hasPermission(permissions, "pipeline", "update", "platform"));

  const exportPipeline = () => {
    const data = {
      name: pipeline.name,
      slug: pipeline.slug,
      description: pipeline.description,
      readme: pipeline.readme,
      category: pipeline.category,
      pipeline_type: pipeline.pipeline_type,
      tags: pipeline.tags,
      is_public: pipeline.is_public,
      // The DAG shape lives at the pipeline level; versions are bindings.
      steps: pipeline.steps,
      edges: pipeline.edges,
      parameters_schema: pipeline.parameters_schema,
      topology_hash: pipeline.topology_hash,
      versions: pipeline.versions.map((v) => ({
        version: v.version,
        status: v.status,
        bindings: v.bindings,
        changelog: v.changelog,
      })),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${pipeline.slug}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <DetailHeader
        name={pipeline.name}
        kind="pipeline"
        breadcrumbRootLabel={pipelinesLabel}
        breadcrumbLabel={pipeline.slug}
        isFollowed={isFollowed(pipeline.id)}
        onToggleFollow={() => toggle(pipeline.id)}
        onEdit={canUpdate ? () => setShowEditModal(true) : undefined}
        onExport={exportPipeline}
      />

      <DetailMetadata
        description={pipeline.description}
        creatorName={pipeline.creator_name || pipeline.created_by_email || pipeline.created_by}
        createdAt={pipeline.created_at}
        updatedByName={pipeline.updated_by ? (pipeline.updated_by_name || pipeline.updated_by) : null}
        updatedAt={pipeline.updated_by ? pipeline.updated_at : null}
        tags={pipeline.tags}
        isPublic={pipeline.is_public}
        orgName={pipeline.org_name}
        badges={
          <>
            <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-sm font-medium text-purple-800">{pipeline.pipeline_type}</span>
            <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-sm font-medium text-blue-700">{pipeline.category}</span>
          </>
        }
      />

      <DetailReadme readme={pipeline.readme} name={pipeline.name} showWhenEmpty />

      {/* Pipeline DAG — the canonical shape. Versions only pin
          tools/params, so the graph is rendered once here, not per version. */}
      {(pipeline.steps?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">Pipeline DAG</span>
            {pipeline.topology_hash && (
              <span
                title="Canonical topology hash — the pipeline's structural identity"
                className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] text-gray-500"
              >
                {pipeline.topology_hash.slice(0, 12)}
              </span>
            )}
          </div>
          <p className="mb-3 text-xs text-gray-500">
            This is the pipeline&apos;s fixed shape. Each version below pins the tool
            versions and parameter values used — it doesn&apos;t change this graph.
          </p>
          <PipelineGraph steps={pipeline.steps as unknown as PipelineStepConfig[]} />
        </div>
      )}

      {/* Run inputs — the run-I/O contract, part of the canonical shape. */}
      {Object.keys(pipelineSchema).length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">Run inputs</span>
          </div>
          <p className="mb-3 text-xs text-gray-500">
            The data you provide at run time. An input&apos;s routing to a step is part of
            the pipeline&apos;s identity (hashed into its topology) and is fixed once defined.
          </p>
          {pipelineRunInputs.length > 0 ? (
            <ul className="divide-y divide-gray-100 rounded-md border border-gray-200">
              {pipelineRunInputs.map((inp) => (
                <li key={inp.name} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="font-mono text-sm text-gray-700">
                    {inp.name}
                    {inp.required && <span className="ml-1 text-red-500" title="required">*</span>}
                  </span>
                  <span className="flex items-center gap-2 text-xs text-gray-500">
                    {inp.type && (
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono">{inp.type}</span>
                    )}
                    {inp.step && <span>&rarr; {inp.step}</span>}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-500">
              No run inputs declared.
            </p>
          )}
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-blue-600 hover:underline">
              Show full parameters schema
            </summary>
            <pre className="mt-1 max-h-72 overflow-auto rounded bg-gray-50 p-3 text-xs">
              {JSON.stringify(pipeline.parameters_schema, null, 2)}
            </pre>
          </details>
        </div>
      )}

      {/* Versions */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div
          role="button"
          tabIndex={0}
          onClick={() => setVersionsOpen(!versionsOpen)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setVersionsOpen(!versionsOpen); } }}
          className="flex w-full cursor-pointer items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">Versions</span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">{sortedVersions.length}</span>
            {canUpdate && (
              <div className="relative group inline-flex">
                <button
                  onClick={(e) => { e.stopPropagation(); setShowVersionModal(true); }}
                  aria-label="Create a new version"
                  className="rounded px-2.5 py-1.5 text-blue-600 bg-blue-50 hover:bg-blue-100 hover:text-blue-700 transition-colors"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                </button>
                <span className="pointer-events-none absolute z-50 w-max max-w-[200px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100 top-full left-0 mt-1">
                  Create a new version (pin tools &amp; parameters)
                </span>
              </div>
            )}
          </div>
          <svg
            className={`h-4 w-4 text-gray-400 transition-transform ${versionsOpen ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
        {versionsOpen && (
          <div className="px-4 pb-4 space-y-3">
            {sortedVersions.map((pv) => (
              <PipelineVersionCard
                key={pv.id}
                version={pv}
                pipelineId={pipeline.id}
                canUpdate={canUpdate}
                onStatusChange={handleVersionStatusChange}
                onStartRun={openRunForVersion}
                onUpdateVersion={setEditVersionId}
              />
            ))}
            {sortedVersions.length === 0 && (
              <p className="text-sm text-gray-500">No versions yet.</p>
            )}
            {statusUpdating && (
              <p className="text-xs text-gray-400">Updating status...</p>
            )}
          </div>
        )}
      </div>

      {/* New Version Modal (bindings over the locked shape) */}
      {showVersionModal && (
        <PipelineVersionEditorModal
          pipeline={pipeline}
          onClose={() => setShowVersionModal(false)}
          onComplete={() => {
            setShowVersionModal(false);
            fetchPipeline();
          }}
        />
      )}

      {/* Update Version Modal — edit a draft/testing version's bindings in place */}
      {editVersionId && (
        <PipelineVersionEditorModal
          pipeline={pipeline}
          version={(pipeline.versions || []).find((v) => v.id === editVersionId) ?? null}
          onClose={() => setEditVersionId(null)}
          onComplete={() => {
            setEditVersionId(null);
            fetchPipeline();
          }}
        />
      )}

      {/* Submit Run Modal */}
      {showRunModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Submit Run — {pipeline.name}
              {(() => {
                const sv = (pipeline.versions || []).find((v) => v.id === selectedVersionId);
                return sv ? ` · v${sv.version}` : "";
              })()}
            </h2>

            {sourceRunId && sourceRunLoaded && (
              <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800 mb-4">
                Pre-filled from run{" "}
                <Link href={`/pipeline-runs/${sourceRunId}`} className="font-mono text-blue-600 hover:underline">
                  {sourceRunId.slice(0, 12)}...
                </Link>
              </div>
            )}

            {(() => {
              const selectedVersion = (pipeline.versions || []).find((v) => v.id === selectedVersionId);
              const schema = (selectedVersion?.parameters_schema ?? {}) as Record<string, unknown>;
              const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
              const required = (schema?.required ?? []) as string[];
              const steps = (selectedVersion?.steps ?? []) as Record<string, unknown>[];

              // A schema property may be "input data" (vs a tunable parameter) and
              // may be assigned to a specific step via x-step; otherwise it stays on
              // the pipeline stop. Both are declared in the pipeline definition.
              const propStepOf = (k: string): string | null => stepOfProp(props[k]);
              const keyIsInput = (k: string): boolean => isInputProp(props[k]);
              const pipelineKeys = Object.keys(props).filter((k) => !propStepOf(k));

              // Render a tunable parameter property (keyed by its own name).
              const renderPropField = (key: string) => {
                const propDef = props[key] || {};
                const isDataset = propDef.format === "dataset" || /dataset/i.test(key);
                return renderParamField({
                  fieldKey: key,
                  label: key,
                  description: propDef.description != null ? String(propDef.description) : undefined,
                  required: required.includes(key),
                  typeHint: isDataset
                    ? "dataset"
                    : propDef.type != null
                      ? String(propDef.type)
                      : undefined,
                  isDataset,
                  propDef,
                });
              };

              // Render an input-data property with Dataset / Upload / Paste tabs.
              const renderInputField = (key: string) => {
                const propDef = props[key] || {};
                const st = dataFieldStates[key] ?? { mode: "dataset" as const, value: "", file: null };
                return (
                  <InputDataField
                    key={key}
                    name={key}
                    description={propDef.description != null ? String(propDef.description) : undefined}
                    required={required.includes(key)}
                    state={st}
                    onChange={(patch) =>
                      setDataFieldStates((prev) => ({
                        ...prev,
                        [key]: { ...(prev[key] ?? { mode: "dataset", value: "", file: null }), ...patch },
                      }))
                    }
                  />
                );
              };

              // Train stops: the pipeline first, then one stop per step.
              const stops = [
                { kind: "pipeline" as const, label: "Pipeline" },
                ...steps.map((s) => ({
                  kind: "step" as const,
                  label: (s.name as string) || "unnamed",
                })),
              ];
              const lastStop = stops.length - 1;
              const stop = Math.min(wizardStop, lastStop);
              const requiredMissing = required.some((k) => {
                if (keyIsInput(k)) {
                  const st = dataFieldStates[k];
                  if (!st) return true;
                  return st.mode === "upload" ? st.file == null : st.value.trim() === "";
                }
                return isEmptyParam(paramValues[k]);
              });

              return (
                <div className="space-y-4">
                  {/* Train stops */}
                  <nav className="flex items-center gap-1 overflow-x-auto pb-1">
                    {stops.map((st, i) => {
                      const active = i === stop;
                      const done = i < stop;
                      return (
                        <div key={i} className="flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setWizardStop(i)}
                            className="flex items-center gap-2"
                          >
                            <span
                              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                                active
                                  ? "bg-blue-600 text-white"
                                  : done
                                    ? "bg-blue-100 text-blue-700"
                                    : "bg-gray-100 text-gray-500"
                              }`}
                            >
                              {st.kind === "pipeline" ? (
                                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                                  <circle cx="12" cy="12" r="3" />
                                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                                </svg>
                              ) : (
                                i
                              )}
                            </span>
                            <span className={`max-w-[110px] truncate text-xs font-medium ${active ? "text-blue-700" : "text-gray-500"}`}>
                              {st.label}
                            </span>
                          </button>
                          {i < lastStop && <span className="mx-1 h-px w-5 bg-gray-200" />}
                        </div>
                      );
                    })}
                  </nav>

                  {/* Stop body */}
                  {stops[stop].kind === "pipeline" ? (
                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Run Name
                          <span className="ml-2 text-xs font-normal text-gray-400">(optional)</span>
                        </label>
                        <input
                          type="text"
                          value={runName}
                          onChange={(e) => setRunName(e.target.value)}
                          placeholder="e.g. BACE1 docking batch 3"
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                          maxLength={255}
                        />
                      </div>
                      {(() => {
                        const inputs = pipelineKeys.filter(keyIsInput);
                        const params = pipelineKeys.filter((k) => !keyIsInput(k));
                        if (inputs.length === 0 && params.length === 0) {
                          return (
                            <p className="text-sm text-gray-500">No pipeline-level inputs or parameters.</p>
                          );
                        }
                        return (
                          <>
                            {inputs.length > 0 && (
                              <div className="space-y-3">
                                <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Input data</h4>
                                {inputs.map(renderInputField)}
                              </div>
                            )}
                            {params.length > 0 && (
                              <div className="space-y-3">
                                <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Parameters</h4>
                                {params.map(renderPropField)}
                              </div>
                            )}
                          </>
                        );
                      })()}
                    </div>
                  ) : (
                    (() => {
                      const s = steps[stop - 1];
                      const stepName = (s.name as string) || "unnamed";
                      const stepParams = (s.parameters as Record<string, unknown>) ?? {};
                      // Projection: the binding's keys select which of the tool
                      // version's parameters to expose; the schema (attached
                      // server-side) supplies type/description/default per key.
                      const stepSchemaProps = ((s.parameters_schema as Record<string, unknown>)
                        ?.properties ?? {}) as Record<string, Record<string, unknown>>;
                      const paramKeys = Object.keys(stepParams);
                      // Top-level schema inputs/params assigned to this step via x-step.
                      const inputKeys = Object.keys(props).filter(
                        (k) => propStepOf(k) === stepName && keyIsInput(k),
                      );
                      const propParamKeys = Object.keys(props).filter(
                        (k) => propStepOf(k) === stepName && !keyIsInput(k),
                      );
                      const nothing =
                        inputKeys.length === 0 && propParamKeys.length === 0 && paramKeys.length === 0;
                      return (
                        <div className="space-y-4">
                          <h3 className="text-sm font-semibold text-gray-700">
                            {stepName}
                            <span className="ml-2 text-xs font-normal text-gray-400">
                              ({(s.tool_slug as string) || "no tool"})
                            </span>
                          </h3>
                          {inputKeys.length > 0 && (
                            <div className="space-y-3">
                              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Input data</h4>
                              {inputKeys.map(renderInputField)}
                            </div>
                          )}
                          {(propParamKeys.length > 0 || paramKeys.length > 0) && (
                            <div className="space-y-3">
                              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Parameters</h4>
                              {propParamKeys.map(renderPropField)}
                              {paramKeys.map((key) => {
                                const nsKey = `${stepName}.${key}`;
                                const def = stepSchemaProps[key] ?? {};
                                const isDataset =
                                  def.format === "dataset" || /dataset/i.test(key);
                                const fallback = stepParams[key] ?? def.default;
                                return renderParamField({
                                  fieldKey: nsKey,
                                  label: key,
                                  description:
                                    def.description != null ? String(def.description) : undefined,
                                  isDataset,
                                  typeHint: isDataset
                                    ? "dataset"
                                    : def.type != null
                                      ? String(def.type)
                                      : undefined,
                                  placeholder: fallback != null ? String(fallback) : "",
                                  propDef: def,
                                });
                              })}
                            </div>
                          )}
                          {nothing && (
                            <p className="text-sm text-gray-500">
                              No configurable inputs or parameters for this step. Defaults will be used.
                            </p>
                          )}
                        </div>
                      );
                    })()
                  )}

                  {submitError && <p className="text-sm text-red-600">{submitError}</p>}

                  {/* Footer navigation */}
                  <div className="flex items-center gap-2 border-t border-gray-100 pt-3">
                    <button
                      type="button"
                      onClick={() => setWizardStop((s) => Math.max(0, s - 1))}
                      disabled={stop === 0}
                      className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40"
                    >
                      Back
                    </button>
                    <span className="text-xs text-gray-400">
                      Step {stop + 1} of {stops.length}
                    </span>
                    <div className="flex-1" />
                    {stop < lastStop ? (
                      <button
                        type="button"
                        onClick={() => setWizardStop((s) => Math.min(lastStop, s + 1))}
                        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                      >
                        Next
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={handleSubmitRun}
                        disabled={submitting || requiredMissing}
                        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                      >
                        {submitting ? "Submitting..." : "Submit"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => { setShowRunModal(false); setSubmitError(null); setWizardStop(0); }}
                      className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* Recent runs */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <DetailRunHistoryHeader
          count={runsTotal}
          open={runsOpen}
          onToggle={() => setRunsOpen(!runsOpen)}
        />
        {runsOpen && (
          <div className="px-4 pb-4">
            {runs.length === 0 ? (
          <p className="text-sm text-gray-500">No runs yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Run ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Version</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Submitted By</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Submitted On</th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {runs.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link href={`/pipeline-runs/${r.id}`} className="font-mono text-sm text-blue-600 hover:underline">
                        {r.id.slice(0, 12)}...
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {r.pipeline_version != null ? `v${r.pipeline_version}` : "\u2014"}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {r.submitted_by_email || r.submitted_by.slice(0, 12) + "..."}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {formatDuration(r.started_at, r.finished_at, r.status)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
          </div>
        )}
      </div>

      {showEditModal && (
        <PipelineMetadataModal
          pipeline={pipeline}
          onClose={() => setShowEditModal(false)}
          onUpdate={fetchPipeline}
        />
      )}
    </div>
  );
}
