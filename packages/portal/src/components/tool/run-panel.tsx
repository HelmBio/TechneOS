"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import DatasetSelector from "@/components/dataset-selector";
import { SchemaForm, collectDefaults } from "@/components/schema-form";
import { API_BASE, apiPost, getToken, type ToolRun, type ToolVersion } from "@/lib/api";

interface Props {
  toolId: string;
  toolSlug: string;
  version: ToolVersion;
  onCancel?: () => void;
}

type InputMode = "dataset" | "upload" | "inline";

interface StagedInputRef {
  id: string;
  parameter_name: string;
  file_name: string;
  file_size: number;
  content_type: string;
  storage_bucket: string;
  storage_key: string;
  source: string;
}

interface FieldState {
  mode: InputMode;
  value: string;
  file: File | null;
  stagedInput: StagedInputRef | null;
}

function propertiesOf(schema: Record<string, unknown> | undefined): Record<string, Record<string, unknown>> {
  if (!schema || typeof schema !== "object") return {};
  const props = (schema as { properties?: unknown }).properties;
  return (props && typeof props === "object" ? (props as Record<string, Record<string, unknown>>) : {});
}

export default function ToolRunPanel({ toolId, toolSlug, version, onCancel }: Props) {
  const router = useRouter();
  const inputProps = propertiesOf(version.input_schema as Record<string, unknown> | undefined);
  const paramProps = propertiesOf(version.parameters_schema as Record<string, unknown> | undefined);
  const paramsSchema = version.parameters_schema as Record<string, unknown> | undefined;

  const dataFieldNames = Object.keys(inputProps);
  const paramFieldNames = Object.keys(paramProps).filter((n) => !(n in inputProps));

  const dataFieldInitial = useMemo(() => {
    const initial: Record<string, FieldState> = {};
    for (const name of dataFieldNames) {
      initial[name] = { mode: "dataset", value: "", file: null, stagedInput: null };
    }
    return initial;
  }, [dataFieldNames]);

  const [dataFieldStates, setDataFieldStates] = useState<Record<string, FieldState>>(dataFieldInitial);

  const [paramValues, setParamValues] = useState<Record<string, unknown>>(() => {
    if (paramFieldNames.length === 0) return {};
    if (!paramsSchema || typeof paramsSchema !== "object") return {};
    const props = (paramsSchema as { properties?: Record<string, Record<string, unknown>> }).properties ?? {};
    return collectDefaults(props);
  });

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const requiredParams = (
    paramsSchema?.required && Array.isArray(paramsSchema.required)
      ? (paramsSchema.required as string[])
      : []
  ) as string[];

  const updateField = (name: string, patch: Partial<FieldState>) => {
    setDataFieldStates((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }));
  };

  async function handleSubmit() {
    setError("");

    // Validate required parameters
    for (const name of requiredParams) {
      if (paramFieldNames.includes(name)) {
        const val = paramValues[name];
        if (val === undefined || val === null || val === "") {
          setError(`"${name}" is required.`);
          return;
        }
      }
    }

    setSubmitting(true);
    try {
      const parameters: Record<string, unknown> = { ...paramValues };
      const inputs: StagedInputRef[] = [];

      for (const [name, state] of Object.entries(dataFieldStates)) {
        if (state.mode === "dataset") {
          if (state.value) parameters[name] = state.value;
        } else if (state.mode === "inline") {
          if (!state.value.trim()) continue;
          const contentType = detectPasteContentType(state.value);
          const staged = await stagePaste(state.value, name, contentType, toolSlug, version.version);
          inputs.push(staged);
        } else if (state.mode === "upload") {
          if (!state.file) continue;
          const staged = await stageInput(state.file, name, toolSlug, version.version);
          inputs.push(staged);
        }
      }

      const data = await apiPost<ToolRun>("/api/v1/tool-runs", {
        tool_id: toolId,
        version_id: version.id,
        parameters,
        inputs,
      });

      router.push(`/tool-runs/${data.id}`);
    } catch (e) {
      setError((e as Error).message || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (dataFieldNames.length === 0 && paramFieldNames.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-white p-6 text-sm text-gray-500">
        This tool has no input or parameter schema yet. Add an <code>input_schema</code>{" "}
        or <code>parameters_schema</code> to a version to enable the Run panel.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {dataFieldNames.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
            Input data
          </h4>
          {dataFieldNames.map((name) => {
            const prop = inputProps[name];
            const state = dataFieldStates[name];
            return (
              <DataField
                key={name}
                name={name}
                description={(prop.description as string | undefined) ?? ""}
                state={state}
                onChange={(patch) => updateField(name, patch)}
              />
            );
          })}
        </div>
      )}

      {paramFieldNames.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold uppercase tracking-wide text-gray-500 mb-3">
            Parameters
          </h4>
          <div className="rounded-lg border border-gray-200 p-4 space-y-4">
            <SchemaForm
              schema={paramsSchema ?? null}
              values={paramValues}
              onChange={setParamValues}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="rounded bg-red-50 border border-red-200 text-sm text-red-700 px-3 py-2">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Submit run"}
        </button>
      </div>
    </div>
  );
}


function DataField({
  name,
  description,
  state,
  onChange,
}: {
  name: string;
  description: string;
  state: FieldState;
  onChange: (patch: Partial<FieldState>) => void;
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
        {description && (
          <span className="ml-2 text-xs font-normal text-gray-500">— {description}</span>
        )}
      </label>

      <div className="mt-1 inline-flex rounded-md border border-gray-200 bg-gray-50 p-0.5 text-xs">
        {tabs.map((t) => (
          <button
            key={t.mode}
            type="button"
            onClick={() => onChange({ mode: t.mode, value: "", file: null, stagedInput: null })}
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
          <DatasetSelector
            value={state.value}
            onChange={(v) => onChange({ value: v })}
          />
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


async function stageInput(
  file: File,
  parameterName: string,
  toolSlug: string,
  toolVersion: number,
): Promise<StagedInputRef> {
  const form = new FormData();
  form.append("file", file);
  form.append("parameter_name", parameterName);
  form.append("tool_slug", toolSlug);
  form.append("tool_version", String(toolVersion));

  const token = getToken();
  const resp = await fetch(`${API_BASE}/api/v1/tool-runs/inputs`, {
    method: "POST",
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({} as Record<string, unknown>));
    throw new Error(
      `Upload failed for ${file.name}: ${(body as { detail?: string }).detail || resp.status}`,
    );
  }
  return (await resp.json()) as StagedInputRef;
}


async function stagePaste(
  content: string,
  parameterName: string,
  contentType: string,
  toolSlug: string,
  toolVersion: number,
): Promise<StagedInputRef> {
  const token = getToken();
  const resp = await fetch(`${API_BASE}/api/v1/tool-runs/inputs/paste`, {
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
      tool_slug: toolSlug,
      tool_version: toolVersion,
    }),
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({} as Record<string, unknown>));
    throw new Error(
      `Paste staging failed: ${(body as { detail?: string }).detail || resp.status}`,
    );
  }
  return (await resp.json()) as StagedInputRef;
}


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
