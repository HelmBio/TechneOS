"use client";

import { useState } from "react";

export interface DataPanelState {
  method: "paste" | "file";
  pasteContent: string;
  uploadResult: unknown;
  uploadedFile: File | null;
}

interface DataPanelProps {
  /** Optional heading; omit when the caller renders its own (e.g. with a
   *  required-field asterisk) so the panel doesn't add a second one. */
  title?: string;
  format?: string;
  uploadFn: (file: File) => Promise<unknown>;
  onChange?: (state: DataPanelState) => void;
}

export function DataPanel({ title, format, uploadFn, onChange }: DataPanelProps) {
  const [method, setMethod] = useState<"paste" | "file">("paste");
  const [pasteContent, setPasteContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<unknown>(null);

  const isBinary = format === "xlsx";

  const handlePasteChange = (text: string) => {
    setPasteContent(text);
    setUploadError(null);
    onChange?.({ method: "paste", pasteContent: text, uploadResult: null, uploadedFile: null });
  };

  const handleMethodChange = (m: "paste" | "file") => {
    setMethod(m);
    setUploadError(null);
    if (m === "paste") {
      onChange?.({ method: "paste", pasteContent, uploadResult: null, uploadedFile: null });
    } else {
      onChange?.({ method: "file", pasteContent: "", uploadResult, uploadedFile: file });
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setUploadError(null);
    setUploading(true);
    try {
      const result = await uploadFn(f);
      setUploadResult(result);
      onChange?.({ method: "file", pasteContent: "", uploadResult: result, uploadedFile: f });
    } catch (err: unknown) {
      let msg = "Failed to upload file";
      if (err && typeof err === "object" && "detail" in err) {
        msg = (err as { detail: string }).detail;
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setUploadError(msg);
      setFile(null);
      setUploadResult(null);
      onChange?.({ method: "file", pasteContent: "", uploadResult: null, uploadedFile: null });
    } finally {
      setUploading(false);
    }
  };

  const removeFile = () => {
    setFile(null);
    setUploadResult(null);
    setUploadError(null);
    onChange?.({ method: "file", pasteContent: "", uploadResult: null, uploadedFile: null });
  };

  return (
    <div className="rounded-lg border border-gray-200 p-4 space-y-4">
      {title && <h3 className="text-sm font-semibold text-gray-800">{title}</h3>}

      <div className="flex gap-2">
        {!isBinary && (
          <button
            type="button"
            onClick={() => handleMethodChange("paste")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${method === "paste" ? "bg-blue-600 text-white" : "border border-gray-300 text-gray-700 hover:bg-gray-50"}`}
          >
            Paste
          </button>
        )}
        <button
          type="button"
          onClick={() => handleMethodChange("file")}
          className={`rounded-md px-3 py-1.5 text-sm font-medium ${method === "file" ? "bg-blue-600 text-white" : "border border-gray-300 text-gray-700 hover:bg-gray-50"}`}
        >
          File Upload
        </button>
      </div>

      {method === "paste" ? (
        <textarea
          value={pasteContent}
          onChange={(e) => handlePasteChange(e.target.value)}
          rows={8}
          placeholder={`Paste ${format || "JSON"} data here...`}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
        />
      ) : (
        <div>
          <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-gray-300 border-dashed rounded-lg cursor-pointer bg-gray-50 hover:bg-gray-100">
            <div className="flex flex-col items-center justify-center pt-5 pb-6">
              <svg className="w-8 h-8 mb-2 text-gray-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              {file ? (
                <div className="text-center">
                  {uploading ? (
                    <>
                      <svg className="w-8 h-8 mb-2 text-blue-500 animate-spin mx-auto" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      <p className="text-sm text-blue-600 font-medium">Uploading...</p>
                    </>
                  ) : uploadResult ? (
                    <>
                      <svg className="w-8 h-8 mb-2 text-green-500 mx-auto" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <p className="text-sm font-medium text-gray-700">{file.name}</p>
                      <p className="text-xs text-gray-500">{(file.size / 1024).toFixed(1)} KB</p>
                    </>
                  ) : (
                    <>
                      <p className="text-sm font-medium text-gray-700">{file.name}</p>
                      <p className="text-xs text-gray-500">{(file.size / 1024).toFixed(1)} KB</p>
                    </>
                  )}
                </div>
              ) : (
                <>
                  <p className="text-sm text-gray-500">Click to upload or drag and drop</p>
                  <p className="text-xs text-gray-400">{format || "Input"} files</p>
                </>
              )}
            </div>
            <input
              type="file"
              className="hidden"
              onChange={handleFileSelect}
            />
          </label>
          {file && !uploading && (
            <button type="button" onClick={removeFile} className="mt-1 text-xs text-red-600 hover:text-red-800">
              Remove file
            </button>
          )}
          {uploadError && (
            <p className="mt-2 text-xs text-red-600">{uploadError}</p>
          )}
        </div>
      )}
    </div>
  );
}
