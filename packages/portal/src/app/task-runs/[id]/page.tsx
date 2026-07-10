"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useLabel } from "@/lib/labels";

import {
  apiGet,
  apiPost,
  apiUploadTaskOutput,
  apiPostTaskAction,
  type HumanTaskRun,
  type TaskRunSubmitPayload,
  type PaginatedResponse,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  DataPanel,
  type DataPanelState,
} from "@/components/task-run/data-panel";
import { isActive, formatFileSize, downloadFile } from "@/lib/run-utils";
import { StatusBadge } from "@/components/run/status-badge";
import { RunFileTable, type RunFile } from "@/components/run/run-file-table";

export default function AssignmentDetailPage() {
  const execTaskLabel = useLabel("exec.task.plural");
  const { id } = useParams<{ id: string }>();
  const { user, loading: authLoading } = useAuth();
  const [assignment, setAssignment] = useState<HumanTaskRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");

  // Submission form state
  const [outputDataState, setOutputDataState] = useState<DataPanelState>({
    method: "paste",
    pasteContent: "",
    uploadResult: null,
    uploadedFile: null,
  });
  const [submitMessage, setSubmitMessage] = useState("");

  // Delegate modal
  const [showDelegate, setShowDelegate] = useState(false);
  const [delegateTo, setDelegateTo] = useState("");
  const [delegateReason, setDelegateReason] = useState("");
  const [delegateError, setDelegateError] = useState("");

  // Cancel modal
  const [showCancel, setShowCancel] = useState(false);
  const [cancelError, setCancelError] = useState("");

  // Decline modal
  const [showDecline, setShowDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");
  const [declineError, setDeclineError] = useState("");

  // Complete modal
  const [showComplete, setShowComplete] = useState(false);
  const [completeError, setCompleteError] = useState("");
  const completeErrorRef = useRef<HTMLDivElement>(null);

  // Users list for delegation (simplified — fetch from API)
  const [users, setUsers] = useState<
    { id: string; email: string; full_name: string | null }[]
  >([]);

  // Activity / action form
  const [actionMessage, setActionMessage] = useState("");
  const [actionFile, setActionFile] = useState<File | null>(null);
  const [replyToId, setReplyToId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionSending, setActionSending] = useState(false);
  const actionInputRef = useRef<HTMLTextAreaElement>(null);
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(
    new Set(),
  );
  const hasInitialExpand = useRef(false);

  const toggleThread = (id: string) => {
    setExpandedThreads((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handlePostAction = async () => {
    if (!actionMessage.trim() && !actionFile) return;
    setActionSending(true);
    setActionError("");
    try {
      await apiPostTaskAction(
        id!,
        actionMessage.trim() || undefined,
        replyToId ?? undefined,
        actionFile ?? undefined,
      );
      setActionMessage("");
      setActionFile(null);
      setReplyToId(null);
      setActionError("");
      fetchAssignment();
    } catch (err: unknown) {
      setActionError(
        err instanceof Error ? err.message : "Failed to post update",
      );
    } finally {
      setActionSending(false);
    }
  };

  const cancelReply = () => {
    setReplyToId(null);
    setActionMessage("");
    setActionFile(null);
  };

  const eventActorName = (ev: HumanTaskRun["event_history"][0]): string => {
    return ev.actor || "System";
  };

  const groups: Record<string, HumanTaskRun["event_history"]> = {};
  const rootEvents: HumanTaskRun["event_history"] = [];
  for (const ev of assignment?.event_history || []) {
    if (ev.parent_event_id) {
      if (!groups[ev.parent_event_id]) groups[ev.parent_event_id] = [];
      groups[ev.parent_event_id].push(ev);
    } else {
      rootEvents.push(ev);
    }
  }
  rootEvents.sort(
    (a, b) =>
      new Date(a.occurred_at || 0).getTime() -
      new Date(b.occurred_at || 0).getTime(),
  );
  for (const key of Object.keys(groups)) {
    groups[key].sort(
      (a, b) =>
        new Date(a.occurred_at || 0).getTime() -
        new Date(b.occurred_at || 0).getTime(),
    );
  }

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAssignment = useCallback(() => {
    if (!id) return;
    apiGet<HumanTaskRun>(`/api/v1/task-runs/${id}`)
      .then((data) => {
        setAssignment(data);
        if (!hasInitialExpand.current) {
          hasInitialExpand.current = true;
          const updates = (data.event_history || []).filter(
            (ev) => ev.action_type === "update" && !ev.parent_event_id,
          );
          if (updates.length > 0) {
            const latest = updates.reduce((a, b) =>
              new Date(a.occurred_at || 0).getTime() >
              new Date(b.occurred_at || 0).getTime()
                ? a
                : b,
            );
            setExpandedThreads(new Set([latest.id]));
          }
        }
      })
      .catch(() => setAssignment(null))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (authLoading || !user) return;
    setLoading(true);
    fetchAssignment();
    apiGet<
      PaginatedResponse<{ id: string; email: string; full_name: string | null }>
    >("/api/v1/users", { limit: "200" })
      .then((data) => setUsers(data.items))
      .catch(() => {});
  }, [user, authLoading, fetchAssignment]);

  // Scroll to the complete-modal error box when it appears.
  useEffect(() => {
    if (completeError) {
      completeErrorRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [completeError]);

  // Poll while active
  useEffect(() => {
    if (!assignment || !isActive(assignment.status)) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(fetchAssignment, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [assignment, fetchAssignment]);

  const doAction = async (
    action: string,
    payload?: Record<string, unknown>,
  ) => {
    if (!id) return;
    setActionLoading(true);
    setError("");
    try {
      await apiPost(`/api/v1/task-runs/${id}/${action}`, payload || {});
      fetchAssignment();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `${action} failed`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDownload = async (file: RunFile) => {
    if (!id) return;
    try {
      const data = await apiGet<{ download_url: string }>(
        `/api/v1/task-runs/${id}/download-output?file_name=${encodeURIComponent(file.file_name)}`,
      );
      await downloadFile(data.download_url, file.file_name);
    } catch {
      setError("Failed to download file");
    }
  };

  const artifactFiles: RunFile[] = (() => {
    const seen = new Set<string>();
    const result: RunFile[] = [];

    const pushIfUnique = (f: RunFile) => {
      if (!seen.has(f.file_name)) {
        seen.add(f.file_name);
        result.push(f);
      }
    };

    (assignment?.inputs || []).forEach((inp) =>
      pushIfUnique({ id: inp.id, file_name: inp.file_name, file_size: inp.file_size, file_type: "input" }),
    );

    if (assignment?.output_data) {
      const attachments = Array.isArray(assignment.output_data.attachments)
        ? assignment.output_data.attachments
        : [];
      attachments.forEach((att: Record<string, unknown>, i: number) =>
        pushIfUnique({
          id: `output-${i}`,
          file_name: String(att.file_name || `file-${i}`),
          file_size: Number(att.file_size || 0),
          file_type: "output",
        }),
      );
    }

    (assignment?.event_history || []).forEach((ev) => {
      const ft = ev.action_type === "update" ? "update" : "output";
      (ev.artifacts || []).forEach((a) =>
        pushIfUnique({ id: a.id, file_name: a.file_name, file_size: a.file_size, file_type: ft }),
      );
    });

    return result;
  })();

  if (authLoading || loading)
    return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>
        .
      </p>
    );
  if (!assignment)
    return <p className="p-8 text-red-500">Assignment not found.</p>;

  const isAssignee = assignment.assigned_user_id === user.id;
  const isCreator = assignment.started_by === user.id;
  const canAccept =
    assignment.status === "pending" &&
    (isAssignee || !assignment.assigned_user_id);
  const canSubmit =
    (assignment.status === "accepted" || assignment.status === "in_progress") &&
    isAssignee;
  const canDecline =
    (assignment.status === "pending" ||
      assignment.status === "accepted" ||
      assignment.status === "in_progress") &&
    isAssignee;
  const canCancel = assignment.status !== "terminal" && isCreator;

  return (
    <div className="space-y-6">
      {/* Breadcrumb: Task Runs / Task Name / v{N} / run id */}
      <div className="flex items-center gap-2 text-sm text-gray-500 mb-3">
        <Link href="/task-runs" className="hover:text-blue-600">
          {execTaskLabel}
        </Link>
        <span>/</span>
        {assignment.tool_id ? (
          <Link
            href={`/tasks/${assignment.tool_slug || assignment.tool_id}`}
            className="hover:text-blue-600"
          >
            {(assignment.tool_slug || "")
              .replace(/-/g, " ")
              .replace(/\b\w/g, (c) => c.toUpperCase())}
          </Link>
        ) : (
          <span>
            {(assignment.tool_slug || "")
              .replace(/-/g, " ")
              .replace(/\b\w/g, (c) => c.toUpperCase())}
          </span>
        )}
        <span>/</span>
        <span className="font-mono">v{assignment.tool_version_num || "?"}</span>
        <span>/</span>
        <span className="font-mono">{assignment.id.slice(0, 8)}…</span>
        <StatusBadge status={assignment.display_status} />
      </div>

      {error ? (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {assignment.escalated_at ? (
        <div className="rounded border border-orange-200 bg-orange-50 p-3 text-sm text-orange-700">
          Escalated to {assignment.escalated_to || "project lead"} on{" "}
          {new Date(assignment.escalated_at).toLocaleString()}
        </div>
      ) : null}

      {/* Actions */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-gray-900">Actions</h2>
          <div className="flex items-center gap-2">
            {canAccept && (
              <button
                onClick={() => doAction("accept")}
                disabled={actionLoading}
                className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {actionLoading ? "..." : "Accept"}
              </button>
            )}
            {canSubmit && (
              <button
                onClick={() => setShowComplete(true)}
                disabled={actionLoading}
                className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {actionLoading ? "..." : "Complete"}
              </button>
            )}
            {canDecline && (
              <button
                onClick={() => setShowDecline(true)}
                disabled={actionLoading}
                className="rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                {actionLoading ? "..." : "Decline"}
              </button>
            )}
            {(canAccept || canSubmit || canDecline) && (
              <button
                onClick={() => setShowDelegate(true)}
                disabled={actionLoading}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Delegate
              </button>
            )}
            {canCancel && (
              <button
                onClick={() => setShowCancel(true)}
                disabled={actionLoading}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                {actionLoading ? "..." : "Cancel"}
              </button>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
            {(assignment.assigned_user_name || assignment.assigned_team_name) && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Assigned To:</span>
                <span className="text-gray-700">
                  {assignment.assigned_user_name || assignment.assigned_team_name}
                </span>
              </div>
            )}
            <div className="flex items-center gap-1">
              <span className="text-gray-400">Priority:</span>
              <span className="text-gray-700 capitalize">
                {assignment.priority || "medium"}
              </span>
            </div>
            {assignment.project_lead_name && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Project Lead:</span>
                <span className="text-gray-700">{assignment.project_lead_name}</span>
              </div>
            )}
            {assignment.due_at && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Due Date:</span>
                <span className="text-gray-700">
                  {new Date(assignment.due_at).toLocaleDateString()}
                </span>
              </div>
            )}
            <div className="flex items-center gap-1">
              <span className="text-gray-400">Started By:</span>
              <span className="text-gray-700">
                {assignment.started_by_name || "—"}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-gray-400">Started On:</span>
              <span className="text-gray-700">
                {new Date(assignment.started_at).toLocaleDateString()}
              </span>
            </div>
            {assignment.finished_by_name && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Finished By:</span>
                <span className="text-gray-700">{assignment.finished_by_name}</span>
              </div>
            )}
            {assignment.finished_at && (
              <div className="flex items-center gap-1">
                <span className="text-gray-400">Finished On:</span>
                <span className="text-gray-700">
                  {new Date(assignment.finished_at).toLocaleDateString()}
                </span>
              </div>
            )}
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Parameters</h2>
        {assignment.input_snapshot &&
        Object.keys(assignment.input_snapshot).length > 0 ? (
          <pre className="overflow-auto max-h-72 rounded bg-gray-50 border border-gray-200 p-3 text-xs">
            {JSON.stringify(assignment.input_snapshot, null, 2)}
          </pre>
        ) : (
          <p className="text-sm text-gray-500">No parameters.</p>
        )}
      </section>

      {/* Artifacts */}
      {artifactFiles.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Artifacts</h2>
          <RunFileTable
            files={artifactFiles}
            onDownload={handleDownload}
            showType={true}
          />
        </section>
      )}

      {/* Event History — full event log for this task run (excluding updates). */}
      {assignment.event_history &&
        assignment.event_history.filter((ev) => ev.action_type !== "update")
          .length > 0 && (
          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">
              Event History
            </h2>
            <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Event
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Actor
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Target
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Detail
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Date
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {assignment.event_history
                    .filter((ev) => ev.action_type !== "update")
                    .map((ev, i) => (
                      <tr key={ev.id || i}>
                        <td className="px-4 py-2 text-sm font-medium text-gray-900 capitalize">
                          {ev.action_type}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700">
                          {ev.actor || "—"}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700">
                          {ev.target || "—"}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-500">
                          {ev.detail || "—"}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-500">
                          {ev.occurred_at
                            ? new Date(ev.occurred_at).toLocaleString()
                            : "—"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

      {/* Discussions — threaded update messages */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-3">
          Discussions
        </h2>

        {/* Update message threads */}
        {rootEvents.filter((ev) => ev.action_type === "update").length > 0 ? (
          <div className="space-y-2">
            {rootEvents
              .filter((ev) => ev.action_type === "update")
              .map((ev) => {
                const open = expandedThreads.has(ev.id);
                const preview = ev.message
                  ? ev.message.length > 80
                    ? ev.message.slice(0, 80) + "…"
                    : ev.message
                  : "(file only)";
                const replyCount = groups[ev.id]?.length || 0;
                return (
                  <div
                    key={ev.id}
                    className="rounded-lg border border-gray-200 bg-white"
                  >
                    {/* Accordion header */}
                    <button
                      onClick={() => toggleThread(ev.id)}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-500 hover:bg-gray-50 rounded-t-lg"
                    >
                      <span className="text-gray-400 w-4">
                        {open ? "▼" : "▶"}
                      </span>
                      <span className="font-medium text-gray-700 shrink-0">
                        {eventActorName(ev)}
                      </span>
                      <span className="truncate text-gray-400">{preview}</span>
                      {replyCount > 0 && (
                        <span className="ml-auto shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                          {replyCount}
                        </span>
                      )}
                      <span className="shrink-0 text-gray-400">
                        {ev.occurred_at
                          ? new Date(ev.occurred_at).toLocaleString()
                          : ""}
                      </span>
                    </button>

                    {/* Accordion content */}
                    {open && (
                      <div className="border-t border-gray-100 px-3 py-2">
                        {ev.message ? (
                          <p className="text-sm text-gray-800 whitespace-pre-wrap">
                            {ev.message}
                          </p>
                        ) : null}
                        {ev.artifacts && ev.artifacts.length > 0 ? (
                          <div className="mt-1.5 space-y-0.5">
                            {ev.artifacts.map((a) => (
                              <button
                                key={a.id}
                                onClick={() =>
                                  handleDownload({ id: a.id, file_name: a.file_name, file_size: a.file_size })
                                }
                                className="text-xs text-blue-600 font-mono hover:text-blue-800 hover:underline"
                              >
                                {a.file_name}
                              </button>
                            ))}
                          </div>
                        ) : null}
                        <div className="mt-1 flex items-center gap-3">
                          {isActive(assignment.status) ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setReplyToId(ev.id);
                                actionInputRef.current?.focus();
                              }}
                              className="text-xs text-gray-400 hover:text-blue-600"
                            >
                              Reply
                            </button>
                          ) : null}
                        </div>
                        {/* Threaded replies */}
                        {groups[ev.id]?.map((reply) => (
                          <div
                            key={reply.id}
                            className="ml-4 mt-2 border-l-2 border-gray-100 pl-3"
                          >
                            <div className="flex items-center justify-between text-xs text-gray-500 mb-0.5">
                              <span className="font-medium text-gray-700">
                                {eventActorName(reply)}
                              </span>
                              <span>
                                {reply.occurred_at
                                  ? new Date(reply.occurred_at).toLocaleString()
                                  : ""}
                              </span>
                            </div>
                            {reply.message ? (
                              <p className="text-sm text-gray-800 whitespace-pre-wrap">
                                {reply.message}
                              </p>
                            ) : null}
                            {reply.artifacts && reply.artifacts.length > 0 ? (
                              <div className="mt-0.5 space-y-0.5">
                                {reply.artifacts.map((a) => (
                                  <button
                                    key={a.id}
                                    onClick={() =>
                                      handleDownload({ id: a.id, file_name: a.file_name, file_size: a.file_size })
                                    }
                                    className="text-xs text-blue-600 font-mono hover:text-blue-800 hover:underline"
                                  >
                                    {a.file_name}
                                  </button>
                                ))}
                              </div>
                            ) : null}
                            {isActive(assignment.status) ? (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setReplyToId(reply.id);
                                  actionInputRef.current?.focus();
                                }}
                                className="mt-0.5 text-xs text-gray-400 hover:text-blue-600"
                              >
                                Reply
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No messages yet.</p>
        )}

        {/* Post update form — shown when the run is active */}
        {isActive(assignment.status) && (
          <div className="mt-4 rounded-lg border border-gray-200 bg-white p-3">
            {replyToId ? (
              <div className="mb-2 flex items-center justify-between text-xs text-blue-600">
                <span>Replying to a message</span>
                <button
                  onClick={cancelReply}
                  className="text-gray-400 hover:text-gray-600"
                >
                  &times; Cancel
                </button>
              </div>
            ) : null}
            <div className="flex gap-2">
              <textarea
                ref={actionInputRef}
                value={actionMessage}
                onChange={(e) => setActionMessage(e.target.value)}
                placeholder={
                  replyToId
                    ? "Write a reply..."
                    : "Post an update, ask a question, or provide a status update..."
                }
                rows={2}
                className="min-h-[2.5rem] flex-1 resize-none rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handlePostAction();
                  }
                }}
              />
              <div className="flex flex-col gap-1.5">
                <label className="flex cursor-pointer items-center justify-center rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">
                  <span className="text-lg leading-none">+</span>
                  <input
                    type="file"
                    className="hidden"
                    onChange={(e) => setActionFile(e.target.files?.[0] || null)}
                  />
                </label>
                <button
                  onClick={() => handlePostAction()}
                  disabled={
                    actionSending || (!actionMessage.trim() && !actionFile)
                  }
                  className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {actionSending ? "..." : "Send"}
                </button>
              </div>
            </div>
            {actionError ? (
              <p className="mt-1 text-xs text-red-600">{actionError}</p>
            ) : null}
            {actionFile ? (
              <p className="mt-1 text-xs text-gray-500">
                Attached: {actionFile.name} ({formatFileSize(actionFile.size)})
              </p>
            ) : null}
          </div>
        )}
      </section>

      {/* Delegate modal */}
      {showDelegate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Delegate Task Run
            </h2>
            {delegateError ? (
              <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {delegateError}
              </div>
            ) : null}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Delegate To
                </label>
                <select
                  value={delegateTo}
                  onChange={(e) => setDelegateTo(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="">Select a user...</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.email}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Reason (optional)
                </label>
                <input
                  type="text"
                  value={delegateReason}
                  onChange={(e) => setDelegateReason(e.target.value)}
                  placeholder="Why are you delegating?"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowDelegate(false);
                  setDelegateError("");
                }}
                className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  if (!delegateTo) {
                    setDelegateError("Please select a user");
                    return;
                  }
                  setActionLoading(true);
                  try {
                    await apiPost(`/api/v1/task-runs/${id}/delegate`, {
                      to_user_id: delegateTo,
                      reason: delegateReason || undefined,
                    });
                    setShowDelegate(false);
                    setDelegateTo("");
                    setDelegateReason("");
                    setDelegateError("");
                    fetchAssignment();
                  } catch (err: unknown) {
                    setDelegateError(
                      err instanceof Error ? err.message : "Delegation failed",
                    );
                  } finally {
                    setActionLoading(false);
                  }
                }}
                disabled={actionLoading || !delegateTo}
                className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {actionLoading ? "Delegating..." : "Delegate"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Decline modal */}
      {showDecline && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Decline Task Run
            </h2>
            {declineError ? (
              <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {declineError}
              </div>
            ) : null}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Reason (optional)
                </label>
                <input
                  type="text"
                  value={declineReason}
                  onChange={(e) => setDeclineReason(e.target.value)}
                  placeholder="Why are you declining?"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowDecline(false);
                  setDeclineError("");
                  setDeclineReason("");
                }}
                className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  setActionLoading(true);
                  try {
                    await apiPost(`/api/v1/task-runs/${id}/decline`, {
                      reason: declineReason || undefined,
                    });
                    setShowDecline(false);
                    setDeclineReason("");
                    setDeclineError("");
                    fetchAssignment();
                  } catch (err: unknown) {
                    setDeclineError(
                      err instanceof Error ? err.message : "Decline failed",
                    );
                  } finally {
                    setActionLoading(false);
                  }
                }}
                disabled={actionLoading}
                className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {actionLoading ? "Declining..." : "Decline"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cancel modal */}
      {showCancel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Cancel Task Run
            </h2>
            {cancelError ? (
              <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {cancelError}
              </div>
            ) : null}
            <p className="text-sm text-gray-600 mb-6">
              Are you sure you want to cancel this task run? This action cannot
              be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowCancel(false);
                  setCancelError("");
                }}
                className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
              <button
                onClick={async () => {
                  setActionLoading(true);
                  try {
                    await apiPost(`/api/v1/task-runs/${id}/cancel`);
                    setShowCancel(false);
                    setCancelError("");
                    fetchAssignment();
                  } catch (err: unknown) {
                    setCancelError(
                      err instanceof Error ? err.message : "Cancel failed",
                    );
                  } finally {
                    setActionLoading(false);
                  }
                }}
                disabled={actionLoading}
                className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {actionLoading ? "Cancelling..." : "Cancel Task Run"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Complete modal */}
      {showComplete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div
            className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl"
            style={{ maxHeight: "90vh", overflowY: "auto" }}
          >
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Complete Task Run
            </h2>
            <div className="space-y-4">
              {/* Output Data section */}
              <DataPanel
                title="Output Data"
                format={
                  ((assignment?.input_snapshot as Record<string, unknown>)
                    ?.output_file_format as string) || ""
                }
                uploadFn={(file) => apiUploadTaskOutput(id!, file)}
                onChange={(state) => {
                  setOutputDataState(state);
                  setCompleteError("");
                }}
              />

              {/* Message box */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Message (optional)
                </label>
                <textarea
                  value={submitMessage}
                  onChange={(e) => {
                    setSubmitMessage(e.target.value);
                    setCompleteError("");
                  }}
                  rows={3}
                  placeholder="Add a completion message..."
                  className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>

            {completeError && (
              <div
                ref={completeErrorRef}
                className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 whitespace-pre-wrap"
              >
                {completeError}
              </div>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowComplete(false);
                  setCompleteError("");
                  setOutputDataState({
                    method: "paste",
                    pasteContent: "",
                    uploadResult: null,
                    uploadedFile: null,
                  });
                  setSubmitMessage("");
                }}
                className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  const fmt =
                    ((assignment?.input_snapshot as Record<string, unknown>)
                      ?.output_file_format as string) || "";
                  setActionLoading(true);
                  try {
                    // Both paste and file produce a finish file artifact: paste
                    // text is uploaded as a file first (mirrors input paste).
                    const attachments: Array<{
                      storage_path: string;
                      file_name: string;
                      content_type: string;
                      file_size: number;
                    }> = [];
                    let parsedOutput: Record<string, unknown> = {};
                    if (outputDataState.method === "paste") {
                      // Try to parse pasted content as structured JSON for downstream tools.
                      try {
                        const parsed = JSON.parse(outputDataState.pasteContent);
                        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                          parsedOutput = parsed;
                        }
                      } catch {
                        // Not JSON — leave as empty object (file-only output).
                      }
                      if (outputDataState.pasteContent.trim()) {
                        const blob = new Blob([outputDataState.pasteContent], {
                          type: "text/plain",
                        });
                        const file = new File(
                          [blob],
                          `output.${fmt || "txt"}`,
                          { type: "text/plain" },
                        );
                        const up = await apiUploadTaskOutput(id!, file);
                        attachments.push({
                          storage_path: up.storage_path,
                          file_name: up.file_name,
                          content_type: up.content_type,
                          file_size: up.file_size,
                        });
                      }
                    } else if (outputDataState.uploadResult) {
                      // Try to read the uploaded file content for structured output.
                      if (outputDataState.uploadedFile) {
                        try {
                          const text = await outputDataState.uploadedFile.text();
                          const parsed = JSON.parse(text);
                          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                            parsedOutput = parsed;
                          }
                        } catch {
                          // Not readable as JSON — leave empty.
                        }
                      }
                      const r = outputDataState.uploadResult as {
                        storage_path: string;
                        file_name: string;
                        content_type: string;
                        file_size: number;
                      };
                      attachments.push({
                        storage_path: r.storage_path,
                        file_name: r.file_name,
                        content_type: r.content_type,
                        file_size: r.file_size,
                      });
                    }

                    const payload: TaskRunSubmitPayload = {
                      output_data: parsedOutput,
                    };
                    if (submitMessage.trim()) {
                      payload.message = submitMessage.trim();
                    }
                    if (attachments.length) {
                      payload.attachments = attachments;
                    }

                    await apiPost(
                      `/api/v1/task-runs/${id}/submit`,
                      payload as unknown as Record<string, unknown>,
                    );
                    setShowComplete(false);
                    setCompleteError("");
                    setOutputDataState({
                      method: "paste",
                      pasteContent: "",
                      uploadResult: null,
                      uploadedFile: null,
                    });
                    setSubmitMessage("");
                    fetchAssignment();
                  } catch (err: unknown) {
                    // Prefer a more detailed error if available from the API (err.detail)
                    const detail =
                      typeof err === "object" &&
                      err !== null &&
                      "detail" in err &&
                      typeof (err as { detail?: unknown }).detail === "string"
                        ? (err as { detail: string }).detail
                        : undefined;
                    const msg =
                      detail ??
                      (err instanceof Error ? err.message : "Submit failed");
                    setCompleteError(msg);
                  } finally {
                    setActionLoading(false);
                  }
                }}
                disabled={actionLoading}
                className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {actionLoading ? "Completing..." : "Complete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
