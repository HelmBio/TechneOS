"use client";

import { useEffect, useMemo, useState } from "react";
import {
  apiGet,
  type Dataset,
  type DatasetWithVersions,
  type DatasetVersion,
  type PaginatedResponse,
} from "@/lib/api";

/**
 * Dropdown that lets users pick a dataset + version.
 *
 * Selected value format: "dataset-slug:v{N}" (e.g. "zinc20:v2").
 *
 * To trigger this selector in JSON Schema-driven parameter forms, set:
 *   { "input_dataset": { "type": "string", "format": "dataset" } }
 */

interface DatasetSelectorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export default function DatasetSelector({
  value,
  onChange,
  placeholder = "Select a dataset...",
  className = "",
}: DatasetSelectorProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [versionsLoading, setVersionsLoading] = useState(false);

  // Resolve current value -> slug + version
  const parsed = useMemo(() => {
    const m = value.match(/^(.+):v(\d+)$/);
    if (!m) return { slug: "", version: "" };
    return { slug: m[1], version: m[2] };
  }, [value]);

  // Fetch dataset list
  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await apiGet<PaginatedResponse<Dataset>>("/api/v1/datasets", {
          skip: "0",
          limit: "200",
        });
        setDatasets(data.items);
      } catch {
        setDatasets([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const selectedDataset = datasets.find((d) => d.slug === parsed.slug) ?? null;

  // Fetch versions when dataset changes
  useEffect(() => {
    (async () => {
      if (!selectedDataset) {
        setVersions([]);
        return;
      }
      setVersionsLoading(true);
      try {
        const data = await apiGet<DatasetWithVersions>(`/api/v1/datasets/${selectedDataset.id}`);
        const ready = (data.versions ?? [])
          .filter((v) => v.status === "ready")
          .sort((a, b) => b.version - a.version);
        setVersions(ready);
      } catch {
        setVersions([]);
      } finally {
        setVersionsLoading(false);
      }
    })();
  }, [selectedDataset?.id]);

  const handleDatasetChange = (slug: string) => {
    if (!slug) {
      onChange("");
      return;
    }
    // Value will be updated once versions load; set slug for now
    // The version effect will auto-select latest
    onChange(slug + ":v0");
    // Trigger version fetch by selecting the dataset
  };

  // Auto-select latest version when versions load and current version is invalid
  useEffect(() => {
    if (!selectedDataset || versions.length === 0) return;
    const currentVer = Number(parsed.version);
    const hasMatch = versions.some((v) => v.version === currentVer);
    if (!hasMatch) {
      onChange(`${selectedDataset.slug}:v${versions[0].version}`);
    }
  }, [versions, selectedDataset, parsed.version, onChange]);

  const handleVersionChange = (versionStr: string) => {
    if (!selectedDataset) return;
    onChange(`${selectedDataset.slug}:v${versionStr}`);
  };

  if (loading) {
    return <p className={`text-sm text-gray-400 ${className}`}>Loading datasets...</p>;
  }

  if (datasets.length === 0) {
    return <p className={`text-sm text-gray-500 ${className}`}>No datasets available.</p>;
  }

  return (
    <div className={`flex gap-2 ${className}`}>
      {/* Dataset picker */}
      <select
        value={parsed.slug}
        onChange={(e) => handleDatasetChange(e.target.value)}
        className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">{placeholder}</option>
        {datasets.map((d) => (
          <option key={d.slug} value={d.slug}>
            {d.name} ({d.slug})
          </option>
        ))}
      </select>

      {/* Version picker */}
      {selectedDataset && (
        versionsLoading ? (
          <span className="w-32 flex items-center text-xs text-gray-400">Loading...</span>
        ) : (
          <select
            value={parsed.version}
            onChange={(e) => handleVersionChange(e.target.value)}
            className="w-36 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {versions.map((v) => (
              <option key={v.version} value={String(v.version)}>
                v{v.version}{v.description ? ` — ${v.description}` : ""}
              </option>
            ))}
            {versions.length === 0 && (
              <option value="" disabled>No ready versions</option>
            )}
          </select>
        )
      )}
    </div>
  );
}
