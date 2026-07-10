"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { apiGet, apiPost, apiPatch, type Dataset, type DatasetWithVersions } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const DATA_TYPES = ["tabular", "molecular", "sequence", "image", "other"];

const FILE_FORMATS = ["csv", "tsv", "sdf", "pdb", "fasta", "parquet", "json", "other"];

interface DatasetFormData {
  name: string;
  slug: string;
  description: string;
  data_type: string;
  file_format: string;
  tags: string;
  metadata: string;
  data_schema: string;
  is_public: boolean;
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
      <NewDatasetPage />
    </Suspense>
  );
}

function NewDatasetPage() {
  const datasetsLabel = useLabel("resource.dataset.plural");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading } = useAuth();

  const fromId = searchParams.get("from");
  const editId = searchParams.get("edit");
  const mode = editId ? "edit" : fromId ? "duplicate" : "create";
  const sourceId = editId || fromId;

  const [loading, setLoading] = useState(!!sourceId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slugManual, setSlugManual] = useState(false);

  const [dataset, setDataset] = useState<DatasetFormData>({
    name: "",
    slug: "",
    description: "",
    data_type: "molecular",
    file_format: "",
    tags: "",
    metadata: "{}",
    data_schema: "{}",
    is_public: false,
  });

  useEffect(() => {
    if (!sourceId || authLoading || !user) return;
    setLoading(true);
    apiGet<DatasetWithVersions>(`/api/v1/datasets/${sourceId}`)
      .then((data) => {
        setDataset({
          name: mode === "duplicate" ? `${data.name} (copy)` : data.name,
          slug: mode === "duplicate" ? `${data.slug}-copy` : data.slug,
          description: data.description || "",
          data_type: data.data_type,
          file_format: data.file_format || "",
          tags: data.tags.join(", "),
          metadata: JSON.stringify(data.metadata || {}, null, 2),
          data_schema: JSON.stringify(data.data_schema || {}, null, 2),
          is_public: data.is_public,
        });
        if (mode === "duplicate" || mode === "edit") {
          setSlugManual(true);
        }
      })
      .catch(() => setError("Failed to load dataset"))
      .finally(() => setLoading(false));
  }, [sourceId, authLoading, user, mode]);

  const handleNameChange = (name: string) => {
    setDataset((prev) => ({
      ...prev,
      name,
      slug: slugManual ? prev.slug : slugify(name),
    }));
  };

  const handleSubmit = async () => {
    setError(null);
    setSaving(true);

    try {
      let parsedMetadata;
      try {
        parsedMetadata = JSON.parse(dataset.metadata || "{}");
      } catch {
        setError("Invalid JSON in Metadata field");
        setSaving(false);
        return;
      }
      let parsedDataSchema: Record<string, unknown> | null;
      try {
        const raw = JSON.parse(dataset.data_schema || "{}") || {};
        parsedDataSchema = Object.keys(raw).length === 0 ? null : raw;
      } catch {
        setError("Invalid JSON in Data Schema field");
        setSaving(false);
        return;
      }

      // Server requires a non-empty data_schema on create. Block the request
      // here with a clear message rather than letting it round-trip as a 422.
      if (mode === "create" && !parsedDataSchema) {
        setError(
          "Data Schema is required — describe the file structure with a JSON Schema object (e.g. { \"type\": \"object\", \"required\": [\"id\"], \"properties\": { \"id\": { \"type\": \"string\" } } })."
        );
        setSaving(false);
        return;
      }

      if (mode === "edit") {
        await apiPatch(`/api/v1/datasets/${editId}`, {
          name: dataset.name,
          description: dataset.description || null,
          data_type: dataset.data_type,
          file_format: dataset.file_format || null,
          tags: dataset.tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
          metadata: parsedMetadata,
          data_schema: parsedDataSchema,
          is_public: dataset.is_public,
        });

        router.push(`/datasets/${editId}`);
      } else {
        const tags = dataset.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean);

        const created = await apiPost<Dataset>("/api/v1/datasets", {
          name: dataset.name,
          slug: dataset.slug,
          description: dataset.description || null,
          data_type: dataset.data_type,
          file_format: dataset.file_format || null,
          tags,
          metadata: parsedMetadata,
          data_schema: parsedDataSchema,
          is_public: dataset.is_public,
        });

        router.push(`/datasets/${created.id}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save dataset";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>{" "}
        to manage datasets.
      </p>
    );
  if (loading) return <p className="p-8 text-gray-500">Loading dataset...</p>;

  return (
    <div className="max-w-3xl space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/datasets" className="hover:text-blue-600">
          {datasetsLabel}
        </Link>
        <span>/</span>
        <span>
          {mode === "edit" ? "Update Dataset" : mode === "duplicate" ? "Duplicate Dataset" : "New Dataset"}
        </span>
      </div>

      <h1 className="text-2xl font-bold text-gray-900">
        {mode === "edit" ? "Update Dataset Definition" : mode === "duplicate" ? "Duplicate Dataset Definition" : "Register New Dataset Definition"}
      </h1>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ── Dataset Metadata ──────────────────────────────────── */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm space-y-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Name *
          </label>
          <input
            type="text"
            value={dataset.name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g. ZINC20 Commercial Subset"
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
              value={dataset.slug}
              onChange={(e) => {
                setSlugManual(true);
                setDataset((prev) => ({ ...prev, slug: e.target.value }));
              }}
              disabled={mode === "edit"}
              placeholder="e.g. zinc20-commercial"
              className={`block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                mode === "edit" ? "bg-gray-100 text-gray-500" : ""
              }`}
            />
            {mode !== "edit" && slugManual && (
              <button
                type="button"
                onClick={() => {
                  setSlugManual(false);
                  setDataset((prev) => ({ ...prev, slug: slugify(prev.name) }));
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
            value={dataset.description}
            onChange={(e) => setDataset((prev) => ({ ...prev, description: e.target.value }))}
            placeholder="Describe the dataset contents, source, and use cases..."
            rows={3}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Data Type & File Format */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Data Type
            </label>
            <select
              value={dataset.data_type}
              onChange={(e) => setDataset((prev) => ({ ...prev, data_type: e.target.value }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {DATA_TYPES.map((dt) => (
                <option key={dt} value={dt}>
                  {dt.charAt(0).toUpperCase() + dt.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              File Format
            </label>
            <select
              value={dataset.file_format}
              onChange={(e) => setDataset((prev) => ({ ...prev, file_format: e.target.value }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {FILE_FORMATS.map((ff) => (
                <option key={ff} value={ff}>
                  {ff.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Tags
          </label>
          <input
            type="text"
            value={dataset.tags}
            onChange={(e) => setDataset((prev) => ({ ...prev, tags: e.target.value }))}
            placeholder="comma-separated, e.g. molecules, commercial, purchasable"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Data Schema (JSON Schema) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Data Schema (JSON Schema) <span className="text-red-600">*</span>
          </label>
          <textarea
            value={dataset.data_schema}
            onChange={(e) => setDataset((prev) => ({ ...prev, data_schema: e.target.value }))}
            placeholder={JSON.stringify({
              type: "object",
              properties: {
                smiles: { type: "string", description: "SMILES notation" },
                molecular_weight: { type: "number", description: "Molecular weight in g/mol" },
              },
              required: ["smiles"],
            }, null, 2)}
            rows={6}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            Required. JSON Schema draft describing expected columns/types — uploads
            are validated against it and downstream tools rely on it to reason
            about the data.
          </p>
        </div>

        {/* Metadata (JSON) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Metadata (JSON)
          </label>
          <textarea
            value={dataset.metadata}
            onChange={(e) => setDataset((prev) => ({ ...prev, metadata: e.target.value }))}
            placeholder='{"source": "https://...", "license": "MIT"}'
            rows={4}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Public */}
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={dataset.is_public}
            onChange={(e) => setDataset((prev) => ({ ...prev, is_public: e.target.checked }))}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Public dataset (visible to all organizations)
        </label>
      </section>

      {/* ── Actions ───────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={saving || !dataset.name || !dataset.slug}
          className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving
            ? "Saving..."
            : mode === "edit"
              ? "Update Dataset"
              : mode === "duplicate"
                ? "Create Copy"
                : "Submit"}
        </button>
        <Link
          href={sourceId ? `/datasets/${sourceId}` : "/datasets"}
          className="rounded-md border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancel
        </Link>
      </div>
    </div>
  );
}
