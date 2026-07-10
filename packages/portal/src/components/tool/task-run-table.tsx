"use client";

import Link from "next/link";

import type { HumanTaskRun } from "@/lib/api";
import { StatusBadge } from "@/components/run/status-badge";

interface TaskRunTableProps {
  taskRuns: HumanTaskRun[];
  showTaskColumn?: boolean;
  emptyMessage?: string;
}

export default function TaskRunTable({ taskRuns, showTaskColumn = false, emptyMessage = "No task runs found." }: TaskRunTableProps) {
  if (taskRuns.length === 0) {
    return <p className="text-sm text-gray-500">{emptyMessage}</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">ID</th>
            {showTaskColumn && <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Task</th>}
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Version</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Assigned To</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Status</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Due Date</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Started By</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Started On</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Finished By</th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">Finished On</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {taskRuns.map((a) => (
            <tr key={a.id} className="hover:bg-gray-50">
              <td className="px-4 py-3">
                <Link href={`/task-runs/${a.id}`} className="font-mono text-xs font-medium text-blue-600 hover:underline">
                  {a.id.slice(0, 8)}
                </Link>
              </td>
              {showTaskColumn && (
                <td className="px-4 py-3 text-sm text-gray-700">
                  {a.tool_slug ? (
                    <Link href={`/tasks/${a.tool_id}`} className="text-blue-600 hover:underline">{a.tool_slug}</Link>
                  ) : "—"}
                </td>
              )}
              <td className="px-4 py-3 text-sm text-gray-600">
                {a.tool_version_num != null ? `v${a.tool_version_num}` : "—"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">
                {a.assigned_user_name || a.assigned_team_name || "—"}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={a.display_status} />
              </td>
              <td className="px-4 py-3 text-sm text-gray-500">
                {a.due_at ? new Date(a.due_at).toLocaleDateString() : "—"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">
                {a.started_by_name || "—"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-500">
                {new Date(a.started_at).toLocaleDateString()}
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">
                {a.finished_by_name || "—"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-500">
                {a.finished_at ? new Date(a.finished_at).toLocaleDateString() : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}