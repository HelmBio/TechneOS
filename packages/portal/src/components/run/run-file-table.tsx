"use client";

import { formatFileSize } from "@/lib/run-utils";

export interface RunFile {
  id: string;
  file_name: string;
  file_size: number;
  file_type?: "input" | "output" | "update";
}

interface RunFileTableProps {
  files: RunFile[];
  onDownload: (file: RunFile) => void;
  showType?: boolean;
  emptyMessage?: string;
}

export function RunFileTable({ files, onDownload, showType = false, emptyMessage = "No files." }: RunFileTableProps) {
  if (files.length === 0) {
    return <p className="text-sm text-gray-500">{emptyMessage}</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {showType && (
              <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                Type
              </th>
            )}
            <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
              File
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Size
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {files.map((f) => (
            <tr key={f.id}>
              {showType && (
                <td className="px-4 py-2">
                  <span
                    className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                      f.file_type === "input"
                        ? "bg-blue-50 text-blue-700"
                        : f.file_type === "output"
                          ? "bg-green-50 text-green-700"
                          : "bg-gray-50 text-gray-600"
                    }`}
                  >
                    {f.file_type || "—"}
                  </span>
                </td>
              )}
              <td className="px-4 py-2 text-sm break-all font-mono">
                <button
                  onClick={() => onDownload(f)}
                  className="text-blue-600 hover:text-blue-800 hover:underline text-left"
                >
                  {f.file_name}
                </button>
              </td>
              <td className="px-4 py-2 text-sm text-gray-600 whitespace-nowrap">
                {f.file_size != null ? formatFileSize(f.file_size) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
