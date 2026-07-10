"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { CollapsibleSection } from "@/components/collapsible-section";
import { FollowIconButton } from "@/components/follow-icon-button";
import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  getToken,
  API_BASE,
  type DatasetWithVersions,
  type DatasetVersion,
  type ObjectInfo,
  type ObjectStoreBucket,
  type SubscriptionCheck,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { hasPermission } from "@/lib/rbac";

const STATUS_COLORS: Record<string, string> = {
  uploading: "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  ready: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-700",
};

const DATA_TYPE_LABELS: Record<string, string> = {
  tabular: "Tabular",
  molecular: "Molecular",
  sequence: "Sequence",
  image: "Image",
  other: "Other",
};

function formatSize(bytes: number): string {
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (bytes < 1024) return `${bytes.toFixed(bytes < 10 && unit !== "B" ? 1 : 0)} ${unit}`;
    bytes /= 1024;
  }
  return `${bytes.toFixed(1)} TB`;
}

function DownloadButton({
  datasetId,
  versionId,
  fileIndex,
  fileName,
}: {
  datasetId: string;
  versionId: string;
  fileIndex: number;
  fileName: string;
}) {
  const [loading, setLoading] = useState(false);

  const handleDownload = async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ download_url: string }>(
        `/api/v1/datasets/${datasetId}/versions/${versionId}/files/${fileIndex}/download`,
      );
      const resp = await fetch(data.download_url);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleDownload}
      onKeyDown={(e) => e.key === "Enter" && handleDownload()}
      aria-disabled={loading}
      className="group relative rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-blue-600 disabled:opacity-50 cursor-pointer"
    >
      {loading ? (
        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" /></svg>
      ) : (
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
      )}
      <span className="pointer-events-none absolute right-0 top-full mt-1 hidden w-max max-w-[200px] rounded bg-gray-800 px-2 py-1 text-xs text-white shadow group-hover:block">
        Download this file
      </span>
    </div>
  );
}

function DownloadAllButton({
  datasetId,
  versionId,
  files,
}: {
  datasetId: string;
  versionId: string;
  files: { file_name: string }[];
}) {
  const [zipping, setZipping] = useState(false);

  const handleDownloadAll = async () => {
    setZipping(true);
    try {
      const JSZip = (await import("jszip")).default;
      const zip = new JSZip();

      for (let i = 0; i < files.length; i++) {
        const data = await apiGet<{ download_url: string }>(
          `/api/v1/datasets/${datasetId}/versions/${versionId}/files/${i}/download`,
        );
        const resp = await fetch(data.download_url);
        const blob = await resp.blob();
        zip.file(files[i].file_name, blob);
      }

      const content = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(content);
      const link = document.createElement("a");
      link.href = url;
      link.download = `dataset-v${versionId.slice(0, 8)}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    } finally {
      setZipping(false);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleDownloadAll}
      onKeyDown={(e) => e.key === "Enter" && handleDownloadAll()}
      aria-disabled={zipping}
      className="group relative rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-blue-600 disabled:opacity-50 cursor-pointer"
    >
      {zipping ? (
        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="12" /></svg>
      ) : (
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="M12 11v6" /><path d="m9 14 3 3 3-3" /></svg>
      )}
      <span className="pointer-events-none absolute right-0 top-full mt-1 hidden w-max max-w-[200px] rounded bg-gray-800 px-2 py-1 text-xs text-white shadow group-hover:block">
        Download all files as zip
      </span>
    </div>
  );
}

interface UploadItem {
  file: File;
  description: string;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
}

function UploadModal({
  datasetId,
  datasetName,
  userOrgId,
  versionId,
  versionNumber,
  initialTab,
  onClose,
  onComplete,
}: {
  datasetId: string;
  datasetName: string;
  userOrgId?: string;
  versionId?: string;
  versionNumber?: number;
  initialTab?: "upload" | "transfer";
  onClose: () => void;
  onComplete: () => void;
}) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [tab, setTab] = useState<"upload" | "transfer">(initialTab || "upload");
  const [buckets, setBuckets] = useState<ObjectStoreBucket[]>([]);
  const [bucketsLoading, setBucketsLoading] = useState(false);
  const [bucketsFetched, setBucketsFetched] = useState(false);
  const [selectedBucketId, setSelectedBucketId] = useState("");
  const [currentPrefix, setCurrentPrefix] = useState("");
  const [bucketFiles, setBucketFiles] = useState<ObjectInfo[]>([]);
  const [bucketFilesLoading, setBucketFilesLoading] = useState(false);
  const [bucketFilesError, setBucketFilesError] = useState("");
  const [selectedFilePaths, setSelectedFilePaths] = useState<Set<string>>(new Set());
  const [transferDescription, setTransferDescription] = useState("");
  const [transferring, setTransferring] = useState(false);
  const [transferError, setTransferError] = useState("");
  const [transferResult, setTransferResult] = useState<string | null>(null);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    setItems((prev) => [
      ...prev,
      ...Array.from(files).map((file) => ({
        file,
        description: "",
        status: "pending" as const,
      })),
    ]);
  };

  const removeItem = (index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index));
  };

  const updateDescription = (index: number, description: string) => {
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, description } : item)));
  };

  const handleUpload = async () => {
    const pending = items.filter((item) => item.status === "pending");
    if (pending.length === 0) return;
    setUploading(true);

    setItems((prev) =>
      prev.map((item) => (item.status === "pending" ? { ...item, status: "uploading" } : item))
    );

    try {
      const formData = new FormData();
      pending.forEach((item) => {
        formData.append("files", item.file);
      });
      const desc = pending.map((item) => item.description).filter(Boolean)[0] || null;
      if (desc) formData.append("description", desc);

      const endpoint = versionId
        ? `${API_BASE}/api/v1/datasets/${datasetId}/versions/${versionId}/files`
        : `${API_BASE}/api/v1/datasets/${datasetId}/versions/batch`;

      const token = getToken();
      const resp = await fetch(endpoint, {
        method: versionId ? "PUT" : "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const detail = err.detail || "Upload failed";
        const errorLines = detail.split("\n").filter(Boolean);
        const fileNameToError: Record<string, string> = {};
        for (const line of errorLines) {
          const match = line.match(/^File '(.+?)'/);
          if (match) fileNameToError[match[1]] = line;
        }

        setItems((prev) =>
          prev.map((item) => {
            if (item.status === "uploading") {
              const fileError = fileNameToError[item.file.name];
              return fileError
                ? { ...item, status: "error", error: fileError }
                : { ...item, status: "pending" };
            }
            return item;
          })
        );
        return;
      }

      setItems((prev) =>
        prev.map((item) => (item.status === "pending" ? { ...item, status: "done" } : item))
      );
      onComplete();
      setItems([]);
    } catch {
      setItems((prev) =>
        prev.map((item) =>
          item.status === "uploading"
            ? { ...item, status: "error", error: "Failed to upload" }
            : item
        )
      );
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    if (tab !== "transfer" || buckets.length > 0 || bucketsLoading || bucketsFetched || !userOrgId) return;
    setBucketsLoading(true);
    apiGet<{ items: ObjectStoreBucket[]; total: number }>(`/api/v1/orgs/${userOrgId}/buckets`)
      .then((data) => {
        setBuckets(data.items);
        if (data.items.length > 0) {
          setSelectedBucketId(data.items[0].id);
          setCurrentPrefix("");
          setBucketFiles([]);
          setSelectedFilePaths(new Set());
        }
      })
      .catch(() => setBuckets([]))
      .finally(() => {
        setBucketsLoading(false);
        setBucketsFetched(true);
      });
  }, [tab, userOrgId, buckets.length, bucketsLoading, bucketsFetched]);

  useEffect(() => {
    setBucketsFetched(false);
    setBuckets([]);
  }, [tab, userOrgId]);

  useEffect(() => {
    if (!selectedBucketId || tab !== "transfer" || !userOrgId) return;
    setBucketFilesLoading(true);
    setBucketFilesError("");
    apiGet<ObjectInfo[]>(`/api/v1/orgs/${userOrgId}/buckets/${selectedBucketId}/files`, { prefix: currentPrefix })
      .then((data) => {
        setBucketFiles(data);
        setBucketFilesError("");
      })
      .catch((err) => {
        console.error("Failed to list bucket files:", err);
        setBucketFiles([]);
        setBucketFilesError(err instanceof Error ? err.message : "Failed to load files");
      })
      .finally(() => setBucketFilesLoading(false));
  }, [selectedBucketId, currentPrefix, tab, userOrgId]);

  function parseBucketListing(objects: ObjectInfo[], prefix: string) {
    const dirs = new Set<string>();
    const files: ObjectInfo[] = [];
    for (const obj of objects) {
      let rel = obj.key;
      if (prefix && rel.startsWith(prefix)) rel = rel.slice(prefix.length);
      const idx = rel.indexOf("/");
      if (idx >= 0) {
        dirs.add(rel.slice(0, idx));
      } else if (rel.length > 0) {
        files.push(obj);
      }
    }
    return { directories: Array.from(dirs).sort(), files: files.sort((a, b) => a.key.localeCompare(b.key)) };
  }

  function goUp() {
    const idx = currentPrefix.lastIndexOf("/", currentPrefix.length - 2);
    setCurrentPrefix(idx >= 0 ? currentPrefix.slice(0, idx + 1) : "");
  }

  function openDir(name: string) {
    setCurrentPrefix(`${currentPrefix}${name}/`);
  }

  function toggleFile(key: string) {
    setSelectedFilePaths((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const handleTransfer = async () => {
    const paths = Array.from(selectedFilePaths);
    if (!selectedBucketId || paths.length === 0) return;
    setTransferring(true);
    setTransferError("");
    setTransferResult(null);
    try {
      const result = await apiPost<DatasetVersion>(
        `/api/v1/datasets/${datasetId}/versions/transfer`,
        {
          source_bucket_id: selectedBucketId,
          file_paths: paths,
          description: transferDescription || null,
        },
      );
      setTransferResult(`Version v${result.version} created — transferring files in the background.`);
      onComplete();
    } catch (err: unknown) {
      setTransferError(err instanceof Error ? err.message : "Transfer request failed");
    } finally {
      setTransferring(false);
    }
  };

  const pendingCount = items.filter((item) => item.status === "pending").length;
  const doneCount = items.filter((item) => item.status === "done").length;
  const errorCount = items.filter((item) => item.status === "error").length;
  const isReplace = !!versionId;
  const title = versionId
    ? `${datasetName} v${versionNumber}: Replace Files`
    : `${datasetName}: New Version`;
  const subtitle = versionId
    ? "Upload files to replace the existing ones in this version"
    : "Upload files to create a new version";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>

        {!isReplace && (
          <div className="flex mb-4 border-b border-gray-200">
            <button
              onClick={() => setTab("upload")}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === "upload"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              Upload Files
            </button>
            <button
              onClick={() => setTab("transfer")}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === "transfer"
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              Transfer from Bucket
            </button>
          </div>
        )}

        {tab === "transfer" ? (
          <div className="space-y-4">
            {transferResult ? (
              <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3">
                <p className="text-sm font-medium text-green-800">{transferResult}</p>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Source Bucket</label>
                  {bucketsLoading ? (
                    <p className="text-sm text-gray-500">Loading buckets...</p>
                  ) : buckets.length === 0 ? (
                    <p className="text-sm text-amber-600">No registered buckets found. Register a bucket in your organization settings first.</p>
                  ) : (
                    <select
                      value={selectedBucketId}
                      onChange={(e) => {
                        setSelectedBucketId(e.target.value);
                        setCurrentPrefix("");
                        setSelectedFilePaths(new Set());
                      }}
                      className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      {buckets.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.name} ({b.bucket_name})
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Files in Bucket
                    {selectedBucketId && !bucketFilesLoading && (
                      <span className="ml-2 text-xs font-normal text-gray-400">
                        ({selectedFilePaths.size} selected)
                      </span>
                    )}
                  </label>
                  <div className="rounded-md border border-gray-200 bg-white max-h-60 overflow-y-auto">
                    {bucketFilesError ? (
                      <p className="px-3 py-6 text-sm text-red-500 text-center">{bucketFilesError}</p>
                    ) : bucketFilesLoading ? (
                      <p className="px-3 py-6 text-sm text-gray-500 text-center">Loading files...</p>
                    ) : bucketFiles.length === 0 && currentPrefix === "" ? (
                      <p className="px-3 py-6 text-sm text-gray-500 text-center">Bucket is empty</p>
                    ) : (
                      <div className="divide-y divide-gray-100">
                        {/* Parent directory */}
                        {currentPrefix && (
                          <button
                            onClick={goUp}
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-600 hover:bg-gray-50"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4 text-amber-500">
                              <path fillRule="evenodd" d="M9.47 4.72a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 1 1-1.06 1.06L10 6.31l-3.72 3.72a.75.75 0 1 1-1.06-1.06l4.25-4.25Z" clipRule="evenodd" />
                            </svg>
                            <span className="font-medium">..</span>
                            <span className="text-xs text-gray-400">(parent)</span>
                          </button>
                        )}
                        {(() => {
                          const { directories, files } = parseBucketListing(bucketFiles, currentPrefix);
                          return (
                            <>
                              {directories.map((dir) => (
                                <button
                                  key={dir}
                                  onClick={() => openDir(dir)}
                                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                                >
                                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4 text-amber-500">
                                    <path d="M3.5 2A1.5 1.5 0 0 0 2 3.5v13A1.5 1.5 0 0 0 3.5 18h13a1.5 1.5 0 0 0 1.5-1.5V7.5A1.5 1.5 0 0 0 16.5 6h-4.586a1.5 1.5 0 0 1-1.06-.44L9.44 4.146A1.5 1.5 0 0 0 8.386 3.5H3.5Z" />
                                  </svg>
                                  <span>{dir}/</span>
                                </button>
                              ))}
                              {files.map((f) => {
                                const isSelected = selectedFilePaths.has(f.key);
                                return (
                                  <label
                                    key={f.key}
                                    className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 cursor-pointer"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isSelected}
                                      onChange={() => toggleFile(f.key)}
                                      className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                    />
                                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4 text-gray-400 flex-shrink-0">
                                      <path d="M3 3.5A1.5 1.5 0 0 1 4.5 2h6.879a1.5 1.5 0 0 1 1.06.44l4.122 4.12A1.5 1.5 0 0 1 17 7.622V16.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 16.5v-13Z" />
                                    </svg>
                                    <span className="truncate">{f.key.replace(currentPrefix, "")}</span>
                                    <span className="ml-auto text-xs text-gray-400 flex-shrink-0">
                                      {f.size > 0 ? `${(f.size / 1024).toFixed(f.size > 1024 * 1024 ? 1 : 0)} KB` : ""}
                                    </span>
                                  </label>
                                );
                              })}
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Version Description</label>
                  <input
                    type="text"
                    value={transferDescription}
                    onChange={(e) => setTransferDescription(e.target.value)}
                    placeholder="Optional description for this version"
                    className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                {transferError && (
                  <p className="text-sm text-red-600">{transferError}</p>
                )}

                <button
                  onClick={handleTransfer}
                  disabled={transferring || !selectedBucketId || selectedFilePaths.size === 0}
                  className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {transferring ? "Requesting Transfer..." : `Transfer ${selectedFilePaths.size} file${selectedFilePaths.size > 1 ? "s" : ""}`}
                </button>
              </>
            )}
          </div>
        ) : (
          <>
            {items.length === 0 ? (
              <label className="cursor-pointer rounded-md border-2 border-dashed border-gray-300 px-4 py-8 text-center hover:border-blue-500 transition-colors block">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="mx-auto h-10 w-10 text-gray-400 mb-2">
                  <path d="M9.25 13.25a.75.75 0 0 0 1.5 0V4.636l2.955 3.129a.75.75 0 0 0 1.09-1.03l-4.25-4.5a.75.75 0 0 0-1.09 0l-4.25 4.5a.75.75 0 1 0 1.09 1.03L9.25 4.636v8.614Z" />
                  <path d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z" />
                </svg>
                <span className="text-sm text-gray-500">Click to select files</span>
                <p className="text-xs text-gray-400 mt-1">SMILES, SDF, PDB, CSV, FASTA, or other molecular data files</p>
                <input
                  type="file"
                  className="hidden"
                  accept=".smi,.smiles,.sdf,.mol,.pdb,.csv,.tsv,.fasta,.fa,.json,.parquet"
                  multiple
                  onChange={(e) => addFiles(e.target.files)}
                />
              </label>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-700">
                    {doneCount}/{items.length} complete
                  </h3>
                  <label className="cursor-pointer rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                    Add more
                    <input
                      type="file"
                      className="hidden"
                      accept=".smi,.smiles,.sdf,.mol,.pdb,.csv,.tsv,.fasta,.fa,.json,.parquet"
                      multiple
                      onChange={(e) => addFiles(e.target.files)}
                    />
                  </label>
                </div>

                {items.map((item, index) => (
                  <div key={index} className="rounded-md border border-gray-200 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className={`h-2 w-2 rounded-full flex-shrink-0 ${
                            item.status === "done"
                              ? "bg-green-500"
                              : item.status === "uploading"
                                ? "bg-blue-500 animate-pulse"
                                : item.status === "error"
                                  ? "bg-red-500"
                                  : "bg-gray-300"
                          }`}
                        />
                        <span className="font-mono text-sm truncate">{item.file.name}</span>
                        <span className="text-xs text-gray-500 flex-shrink-0">({(item.file.size / 1024).toFixed(1)} KB)</span>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-xs font-medium text-gray-500 capitalize">{item.status}</span>
                        {item.status === "pending" && (
                          <button
                            onClick={() => removeItem(index)}
                            className="text-gray-400 hover:text-red-500"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </div>

                    {item.status === "error" && item.error && (
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs text-red-600">{item.error}</p>
                        <button
                          onClick={() => removeItem(index)}
                          className="text-red-400 hover:text-red-600 flex-shrink-0"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
                          </svg>
                        </button>
                      </div>
                    )}

                    {item.status === "pending" && !versionId && (
                      <input
                        type="text"
                        value={item.description}
                        onChange={(e) => updateDescription(index, e.target.value)}
                        placeholder="Version description (optional)"
                        className="block w-full rounded-md border border-gray-300 px-2 py-1 text-xs shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    )}
                  </div>
                ))}

                {pendingCount > 0 && (
                  <button
                    onClick={handleUpload}
                    disabled={uploading}
                    className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {uploading ? "Uploading..." : `Upload ${pendingCount} file${pendingCount > 1 ? "s" : ""}`}
                  </button>
                )}

                {errorCount > 0 && pendingCount === 0 && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        setItems((prev) =>
                          prev.map((item) =>
                            item.status === "error" ? { ...item, status: "pending" as const } : item
                          )
                        );
                        setTimeout(() => handleUpload(), 0);
                      }}
                      disabled={uploading}
                      className="rounded-md bg-red-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Retry {errorCount} failed
                    </button>
                    <button
                      onClick={() => setItems((prev) => prev.filter((item) => item.status !== "error"))}
                      className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
                    >
                      Clear all failed
                    </button>
                  </div>
                )}

                {doneCount === items.length && errorCount === 0 && (
                  <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3">
                    <p className="text-sm font-medium text-green-800">All files uploaded successfully!</p>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function VersionCard({
  version,
  datasetId,
  defaultExpanded = false,
  onOpenReplace,
  onDelete,
  onRetryTransfer,
}: {
  version: DatasetVersion;
  datasetId: string;
  defaultExpanded?: boolean;
  onOpenReplace: () => void;
  onDelete?: () => void;
  onRetryTransfer?: () => void;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fileCount = version.files.length;
  const totalSize = version.files.reduce((sum, f) => sum + f.file_size, 0);

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
      >
          <div className="flex items-center gap-3">
            <span className="font-medium text-gray-900">v{version.version}</span>
            {version.status !== "ready" && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[version.status] || "bg-gray-100"}`}
              >
                {version.status}
              </span>
            )}
            <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">{formatSize(totalSize)} ({fileCount} file{fileCount > 1 ? "s" : ""})</span>
            {version.status === "ready" && fileCount > 1 && (
              <div onClick={(e) => e.stopPropagation()}>
                <DownloadAllButton
                  datasetId={datasetId}
                  versionId={version.id}
                  files={version.files}
                />
              </div>
            )}
            {version.status !== "ready" && version.transfer_method !== "transfer" && (
              <div onClick={(e) => { e.stopPropagation(); onOpenReplace(); }} className="group relative rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 cursor-pointer">
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
                <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[100px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                  Replace files
                </span>
              </div>
            )}

            {version.status !== "ready" && (
              <>
                {onRetryTransfer && version.transfer_method === "transfer" && (
                  <div onClick={(e) => { e.stopPropagation(); onRetryTransfer(); }} className="group relative rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 cursor-pointer">
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.69-3L3 21" /><path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.69 3L21 3" /><path d="M12 7v5l3 3" /></svg>
                    <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[120px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                      Retry transfer
                    </span>
                  </div>
                )}
                {onDelete && (
                  <div onClick={(e) => { e.stopPropagation(); setShowDeleteModal(true); }} className="group relative rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-600 cursor-pointer">
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /></svg>
                    <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[100px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                      Delete version
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        <span className="text-sm text-gray-500">
          {version.updated_by_name || version.creator_name || version.updated_by || version.created_by} · {version.updated_at ? new Date(version.updated_at).toLocaleDateString() : new Date(version.created_at).toLocaleDateString()}
        </span>
      </button>

      {onDelete && showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowDeleteModal(false)}>
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-semibold text-gray-900">Delete version</h3>
            <p className="mt-2 text-sm text-gray-600">
              Are you sure you want to delete v{version.version}? This action cannot be undone.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setShowDeleteModal(false)}
                disabled={deleting}
                className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  if (deleting) return;
                  setDeleting(true);
                  try {
                    await apiDelete(`/api/v1/datasets/${datasetId}/versions/${version.id}`);
                    setShowDeleteModal(false);
                    onDelete();
                  } catch {
                    setDeleting(false);
                  }
                }}
                disabled={deleting}
                className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-4 space-y-3">
          <div className="space-y-1">
            {version.files.map((f, i) => (
              <div key={i} className="flex items-center justify-between text-sm py-1 px-2 rounded bg-gray-50">
                <span className="font-mono text-gray-900 truncate mr-4">{f.file_name}</span>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-xs text-gray-500">{formatSize(f.file_size)}</span>
                  {version.status === "ready" && (
                    <DownloadButton
                      datasetId={datasetId}
                      versionId={version.id}
                      fileIndex={i}
                      fileName={f.file_name}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
          {version.description && (
            <p className="text-sm text-gray-600">{version.description}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function DatasetDetailPage() {
  const datasetsLabel = useLabel("resource.dataset.plural");
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading, permissions } = useAuth();
  const [dataset, setDataset] = useState<DatasetWithVersions | null>(null);
  const [loading, setLoading] = useState(true);
  const [subCheck, setSubCheck] = useState<SubscriptionCheck | null>(null);
  const [subLoading, setSubLoading] = useState(false);

  const canEdit = hasPermission(permissions, "dataset", "update", "own");
  const [showEditModal, setShowEditModal] = useState(false);
  const [uploadModal, setUploadModal] = useState<{ versionId?: string; versionNumber?: number; initialTab?: "upload" | "transfer" } | null>(null);

  const fetchDataset = useCallback(() => {
    if (!id) return;
    setLoading(true);
    apiGet<DatasetWithVersions>(`/api/v1/datasets/${id}`)
      .then(setDataset)
      .catch(() => setDataset(null))
      .finally(() => setLoading(false));
  }, [id]);

  const fetchSubscription = useCallback(() => {
    if (!id) return;
    apiGet<SubscriptionCheck>("/api/v1/subscriptions/check", {
      resource_type: "dataset",
      resource_id: id,
    })
      .then(setSubCheck)
      .catch(() => setSubCheck(null));
  }, [id]);

  useEffect(() => {
    if (authLoading || !user) return;
    fetchDataset();
    fetchSubscription();
  }, [user, authLoading, fetchDataset, fetchSubscription]);

  // Poll for status transitions on transfer-created versions
  useEffect(() => {
    if (!dataset) return;
    const hasPending = dataset.versions.some(
      (v) => v.transfer_method === "transfer" && v.status !== "ready" && v.status !== "failed",
    );
    if (!hasPending) return;
    const id = setInterval(fetchDataset, 10_000);
    return () => clearInterval(id);
  }, [dataset, fetchDataset]);

  const handleFollow = async () => {
    if (!id) return;
    setSubLoading(true);
    try {
      if (subCheck?.subscribed && subCheck.subscription_id) {
        await apiDelete(`/api/v1/subscriptions/${subCheck.subscription_id}`);
      } else {
        await apiPost("/api/v1/subscriptions", {
          resource_type: "dataset",
          resource_id: id,
        });
      }
      fetchSubscription();
    } catch {
      // ignore
    } finally {
      setSubLoading(false);
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
        to view datasets.
      </p>
    );
  if (loading) return <p className="p-8 text-gray-500">Loading dataset...</p>;
  if (!dataset) return <p className="p-8 text-red-500">Dataset not found.</p>;

  const totalSize = dataset.versions.reduce((acc, v) => {
    if (v.files && v.files.length > 0) {
      return acc + v.files.reduce((sum, f) => sum + f.file_size, 0);
    }
    return acc;
  }, 0);
  const totalFileCount = dataset.versions.reduce((acc, v) => {
    if (v.files && v.files.length > 0) return acc + v.files.length;
    return acc;
  }, 0);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
          <Link href="/datasets" className="hover:text-blue-600">
            {datasetsLabel}
          </Link>
          <span>/</span>
          <span>{dataset.slug}</span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900">{dataset.name}</h1>
            <FollowIconButton
              followed={subCheck?.subscribed ?? false}
              loading={subLoading}
              onClick={handleFollow}
              placement="below"
            />
          </div>
          <div className="flex items-center gap-1">
            {canEdit && (
              <button
                onClick={() => setShowEditModal(true)}
                className="group relative rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[120px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
                  Update dataset definition
                </span>
              </button>
            )}
            <button
            onClick={() => {
              const data = {
                id: dataset.id,
                name: dataset.name,
                slug: dataset.slug,
                description: dataset.description,
                data_type: dataset.data_type,
                file_format: dataset.file_format,
                metadata: dataset.metadata,
                is_public: dataset.is_public,
                tags: dataset.tags,
                org_id: dataset.org_id,
                created_by: dataset.created_by,
                creator_name: dataset.creator_name,
                updated_by: dataset.updated_by,
                updated_by_name: dataset.updated_by_name,
                created_at: dataset.created_at,
                updated_at: dataset.updated_at,
                versions: dataset.versions.map((v) => ({
                  version: v.version,
                  id: v.id,
                  description: v.description,
                  status: v.status,
                  created_at: v.created_at,
                  updated_at: v.updated_at,
                  created_by: v.created_by,
                  creator_name: v.creator_name,
                  updated_by: v.updated_by,
                  updated_by_name: v.updated_by_name,
                  files: v.files,
                })),
              };
              const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${dataset.slug}.json`;
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            }}
            className="group relative rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 18l6-6-6-6" /><path d="M8 6l-6 6 6 6" /></svg>
            <span className="pointer-events-none absolute top-full right-0 mt-1 w-max max-w-[150px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100">
              Export dataset definition as JSON
            </span>
          </button>
          </div>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <code className="rounded bg-gray-100 px-2 py-0.5 text-sm font-mono text-gray-600">{dataset.slug}</code>
          <span className="text-xs text-gray-400">Reference this slug in pipelines and agents</span>
        </div>
        {dataset.description && (
          <p className="mt-1 text-gray-600">{dataset.description}</p>
        )}
        <div className="mt-3 flex items-center gap-2 flex-wrap">
            <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
              {DATA_TYPE_LABELS[dataset.data_type] || dataset.data_type}
            </span>
            {dataset.file_format && (
              <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-800">
                {dataset.file_format.toUpperCase()}
              </span>
            )}
            {dataset.is_public && (
              <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
                Public
              </span>
            )}
            {dataset.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600"
              >
                {tag}
              </span>
            ))}
        </div>
      </div>

      {/* Data Schema (collapsible) */}
      <CollapsibleSection title="Data Schema" defaultOpen={false}>
        {dataset.data_schema && Object.keys(dataset.data_schema).length > 0 ? (
          <pre className="rounded-md bg-gray-50 p-3 text-xs font-mono text-gray-700 overflow-x-auto">{JSON.stringify(dataset.data_schema, null, 2)}</pre>
        ) : (
          <p className="text-sm text-gray-400 italic">No data schema defined</p>
        )}
      </CollapsibleSection>

      {/* Metadata (collapsible) */}
      {dataset.metadata && Object.keys(dataset.metadata).length > 0 && (
        <CollapsibleSection title="Metadata" defaultOpen={false}>
          <pre className="rounded-md bg-gray-50 p-3 text-xs font-mono text-gray-700 overflow-x-auto">{JSON.stringify(dataset.metadata, null, 2)}</pre>
        </CollapsibleSection>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Files</p>
          <p className="text-sm font-bold text-gray-900">{formatSize(totalSize)} in {totalFileCount} file{totalFileCount > 1 ? "s" : ""}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Organization</p>
          <p className="text-sm font-bold text-gray-900">{dataset.org_name || dataset.org_id}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Creation</p>
          <p className="text-sm font-bold text-gray-900">{dataset.creator_name || dataset.created_by} on {new Date(dataset.created_at).toLocaleDateString()}</p>
        </div>
        {dataset.updated_by && (
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="text-sm text-gray-500">Update</p>
            <p className="text-sm font-bold text-gray-900">{dataset.updated_by_name || dataset.updated_by} on {new Date(dataset.updated_at).toLocaleDateString()}</p>
          </div>
        )}
      </div>

      {/* Version history */}
      <CollapsibleSection title="Versions" defaultOpen={true} after={
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">{dataset.versions.length}</span>
          {hasPermission(permissions, "dataset", "create", "*") && (
            <div className="relative group inline-flex">
              <button
                onClick={(e) => { e.stopPropagation(); setUploadModal({}); }}
                className="rounded p-1 text-blue-600 bg-blue-50 hover:bg-blue-100 hover:text-blue-700 transition-colors"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </button>
              <span className="pointer-events-none absolute z-50 w-max max-w-[160px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100 top-full right-0 mt-1">
                Add a new version
              </span>
            </div>
          )}
        </div>
      }>
        <div className="space-y-3">
          {dataset.versions.length === 0 ? (
            <p className="text-sm text-gray-500">No versions yet.</p>
          ) : (
            dataset.versions.map((v, i) => (
              <VersionCard key={v.id} version={v} datasetId={dataset.id} defaultExpanded={i === 0} onOpenReplace={() => setUploadModal({ versionId: v.id, versionNumber: v.version })} onDelete={() => fetchDataset()} onRetryTransfer={async () => { try { await apiPost(`/api/v1/datasets/${dataset.id}/versions/${v.id}/retry-transfer`); fetchDataset(); } catch {} }} />
            ))
          )}
        </div>
      </CollapsibleSection>

      {uploadModal && (
        <UploadModal
          datasetId={dataset.id}
          datasetName={dataset.name}
          userOrgId={user?.org_id}
          versionId={uploadModal.versionId}
          versionNumber={uploadModal.versionNumber}
          initialTab={uploadModal.initialTab}
          onClose={() => setUploadModal(null)}
          onComplete={() => { fetchDataset(); setUploadModal(null); }}
        />
      )}

      {showEditModal && (
        <EditMetadataModal
          dataset={dataset}
          onClose={() => setShowEditModal(false)}
          onUpdate={fetchDataset}
        />
      )}
    </div>
  );
}

function EditMetadataModal({
  dataset,
  onClose,
  onUpdate,
}: {
  dataset: DatasetWithVersions;
  onClose: () => void;
  onUpdate: () => void;
}) {
  const [name, setName] = useState(dataset.name);
  const [slug, setSlug] = useState(dataset.slug);
  const [description, setDescription] = useState(dataset.description || "");
  const [dataType, setDataType] = useState(dataset.data_type);
  const [fileFormat, setFileFormat] = useState(dataset.file_format || "");
  const [tags, setTags] = useState(dataset.tags.join(", "));
  const [metadataJson, setMetadataJson] = useState(JSON.stringify(dataset.metadata || {}, null, 2));
  const [dataSchemaJson, setDataSchemaJson] = useState(JSON.stringify(dataset.data_schema || {}, null, 2));
  const [isPublic, setIsPublic] = useState(dataset.is_public);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      let parsedMetadata;
      try {
        parsedMetadata = JSON.parse(metadataJson);
      } catch {
        setError("Invalid JSON in Metadata field");
        setSaving(false);
        return;
      }
      let parsedDataSchema: Record<string, unknown> | null;
      try {
        const raw = JSON.parse(dataSchemaJson) || {};
        parsedDataSchema = Object.keys(raw).length === 0 ? null : raw;
      } catch {
        setError("Invalid JSON in Data Schema field");
        setSaving(false);
        return;
      }
      await apiPatch(`/api/v1/datasets/${dataset.id}`, {
        name,
        slug,
        description: description || null,
        data_type: dataType,
        file_format: fileFormat || null,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        metadata: parsedMetadata,
        data_schema: parsedDataSchema,
        is_public: isPublic,
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
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Update Dataset Definition</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700">Name</label>
            <p className="mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{dataset.name}</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Slug</label>
            <p className="mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-600">{dataset.slug}</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700">Data Type</label>
              <select
                value={dataType}
                onChange={(e) => setDataType(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="tabular">Tabular</option>
                <option value="molecular">Molecular</option>
                <option value="sequence">Sequence</option>
                <option value="image">Image</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">File Format</label>
              <select
                value={fileFormat}
                onChange={(e) => setFileFormat(e.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="csv">CSV</option>
                <option value="tsv">TSV</option>
                <option value="sdf">SDF</option>
                <option value="pdb">PDB</option>
                <option value="fasta">FASTA</option>
                <option value="parquet">Parquet</option>
                <option value="json">JSON</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Tags</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="comma-separated, e.g. molecules, commercial, purchasable"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Data Schema (JSON Schema)</label>
            <textarea
              value={dataSchemaJson}
              onChange={(e) => setDataSchemaJson(e.target.value)}
              rows={4}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-500">
              Optional JSON Schema describing expected columns/types. Used to validate uploaded files.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Metadata (JSON)</label>
            <textarea
              value={metadataJson}
              onChange={(e) => setMetadataJson(e.target.value)}
              rows={4}
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
            Public dataset (visible to all organizations)
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
