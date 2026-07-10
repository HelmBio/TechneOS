"use client";

export function DetailRunHistoryHeader({
  count,
  open,
  onToggle,
}: {
  count: number;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
      className="flex w-full cursor-pointer items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-gray-900">Run History</span>
        {count > 0 && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">{count}</span>
        )}
      </div>
      <svg
        className={`h-4 w-4 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
      </svg>
    </div>
  );
}
