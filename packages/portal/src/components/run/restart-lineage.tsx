"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { formatFileSize, downloadFile } from "@/lib/run-utils";

interface RestartLineageProps {
  restartedFrom: string;
  runType: "tool" | "pipeline";
  parameters: Record<string, unknown>;
}

interface ParentFile {
  id: string;
  file_name: string;
  file_size: number;
}

export function RestartLineage({ restartedFrom, runType, parameters }: RestartLineageProps) {
  const [open, setOpen] = useState(false);
  const [inputFiles, setInputFiles] = useState<ParentFile[] | null>(null);
  const [loadingFiles, setLoadingFiles] = useState(false);

  const basePath = runType === "tool" ? "tool-runs" : "pipeline-runs";

  const fetchParentInputFiles = useCallback(async () => {
    if (inputFiles !== null) return;
    setLoadingFiles(true);
    try {
      const parent = await apiGet<{ artifacts: Array<{ id: string; file_name: string; file_size: number; io_type?: string }> }>(
        `/api/v1/${basePath}/${restartedFrom}`,
      );
      const artifacts = parent.artifacts || [];
      const files = (runType === "tool"
        ? artifacts.filter((a) => a.io_type === "input")
        : artifacts
      ).map((a) => ({ id: a.id, file_name: a.file_name, file_size: a.file_size }));
      setInputFiles(files);
    } catch {
      setInputFiles([]);
    } finally {
      setLoadingFiles(false);
    }
  }, [basePath, restartedFrom, runType, inputFiles]);

  useEffect(() => {
    if (open) fetchParentInputFiles();
  }, [open, fetchParentInputFiles]);

  async function handleDownload(file: ParentFile) {
    const data = await apiGet<{ download_url: string }>(
      `/api/v1/${basePath}/${restartedFrom}/artifacts/${file.id}/download`,
    );
    await downloadFile(data.download_url, file.file_name);
  }

  const hasParams = Object.keys(parameters).length > 0;

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-blue-800"
      >
        <span className="text-blue-400">{open ? "▾" : "▸"}</span>
        <span>
          Restarted from{" "}
          <Link
            href={`/${basePath}/${restartedFrom}`}
            className="font-mono text-blue-600 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {restartedFrom.split("-")[0]}…
          </Link>
        </span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-blue-200 px-4 py-3">
          {hasParams && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-blue-700">Parameters</h4>
              <pre className="max-h-60 overflow-auto rounded border border-blue-100 bg-white p-3 text-xs">
                {JSON.stringify(parameters, null, 2)}
              </pre>
            </div>
          )}

          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-blue-700">
              {runType === "tool" ? "Input Files" : "Artifacts"} (from parent run)
            </h4>
            {loadingFiles ? (
              <p className="text-xs text-blue-600">Loading…</p>
            ) : !inputFiles || inputFiles.length === 0 ? (
              <p className="text-xs text-blue-600">
                {runType === "tool" ? "No input files." : "No artifacts."}
              </p>
            ) : (
              <div className="overflow-hidden rounded border border-blue-100 bg-white">
                <table className="w-full text-xs">
                  <tbody>
                    {inputFiles.map((f) => (
                      <tr key={f.id} className="border-t border-blue-50 first:border-t-0">
                        <td className="px-3 py-1.5 text-gray-700">{f.file_name}</td>
                        <td className="px-3 py-1.5 text-right text-gray-400">{formatFileSize(f.file_size)}</td>
                        <td className="px-3 py-1.5 text-right">
                          <button
                            onClick={() => handleDownload(f)}
                            className="text-blue-600 hover:underline"
                          >
                            Download
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
