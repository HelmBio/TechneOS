"use client";

/**
 * A small bookmark-icon button for follow/unfollow with a tooltip.
 *
 * Props:
 *  - followed: whether the resource is currently followed
 *  - loading:  disable button while toggling
 *  - onClick:  toggle handler
 *  - className: optional extra classes on the outer wrapper
 */
export function FollowIconButton({
  followed,
  loading = false,
  onClick,
  className = "",
  placement = "above",
}: {
  followed: boolean;
  loading?: boolean;
  onClick: () => void;
  className?: string;
  placement?: "above" | "below";
}) {
  return (
    <div className={`relative group inline-flex ${className}`}>
      <button
        onClick={onClick}
        disabled={loading}
        aria-label={followed ? "Unsubscribe from notifications" : "Subscribe for notifications"}
        className={`rounded-full p-1.5 transition-colors ${
          loading
            ? "cursor-wait opacity-50"
            : followed
              ? "text-blue-600 hover:bg-red-50 hover:text-red-500"
              : "text-gray-400 hover:bg-blue-50 hover:text-blue-600"
        }`}
      >
        {followed ? (
          /* Solid bookmark — following */
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M6.32 2.577a49.255 49.255 0 0111.36 0c1.497.174 2.57 1.46 2.57 2.93V21a.75.75 0 01-1.085.67L12 18.089l-7.165 3.583A.75.75 0 013.75 21V5.507c0-1.47 1.073-2.756 2.57-2.93z"
              clipRule="evenodd"
            />
          </svg>
        ) : (
          /* Outline bookmark — not following */
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z"
            />
          </svg>
        )}
      </button>
      {/* Tooltip */}
      <span
        className={`pointer-events-none absolute z-50 w-max max-w-[200px] whitespace-normal rounded bg-gray-900 px-2 py-1 text-xs text-white opacity-0 transition-opacity group-hover:opacity-100 ${
          placement === "below"
            ? "top-full right-0 mt-1"
            : "-top-8 right-0"
        }`}
      >
        {loading ? "..." : followed ? "Unsubscribe from notifications" : "Subscribe for notifications"}
      </span>
    </div>
  );
}
