import { RUN_STATUS_COLORS } from "@/lib/run-utils";

interface StatusBadgeProps {
  status: string;
  className?: string;
  capitalize?: boolean;
}

export function StatusBadge({ status, className = "", capitalize = true }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${capitalize ? "capitalize" : ""} ${RUN_STATUS_COLORS[status] || "bg-gray-100 text-gray-800"} ${className}`}
    >
      {status}
      {status === "running" && (
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
      )}
    </span>
  );
}
