"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";

interface NewResourceButtonProps {
  href: string;
  tooltip: string;
}

export function NewResourceButton({ href, tooltip }: NewResourceButtonProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [align, setAlign] = useState<"center" | "left" | "right">("center");
  const buttonRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (showTooltip && buttonRef.current) {
      const button = buttonRef.current;
      // Deferred to a microtask so the alignment update isn't a direct
      // synchronous setState call inside the effect body.
      queueMicrotask(() => {
        const rect = button.getBoundingClientRect();
        const tooltipWidth = tooltip.length * 7.2 + 24;
        const spaceRight = window.innerWidth - rect.right;
        const spaceLeft = rect.left;

        if (spaceRight < tooltipWidth && spaceLeft > spaceRight) {
          setAlign("right");
        } else if (spaceRight < tooltipWidth) {
          setAlign("left");
        } else {
          setAlign("center");
        }
      });
    }
  }, [showTooltip, tooltip]);

  return (
    <div className="relative inline-block">
      <Link
        ref={buttonRef}
        href={href}
        className="group inline-flex items-center rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onFocus={() => setShowTooltip(true)}
        onBlur={() => setShowTooltip(false)}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-5 w-5"
        >
          <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
        </svg>
      </Link>
      {showTooltip && (
        <div
          className={`absolute top-full mt-2 w-max rounded-md bg-gray-900 px-3 py-1.5 text-xs text-white shadow-lg opacity-100 transition-opacity z-50 whitespace-nowrap ${
            align === "left"
              ? "left-0"
              : align === "right"
              ? "right-0"
              : "left-1/2 -translate-x-1/2"
          }`}
        >
          {tooltip}
          <div
            className={`absolute ${
              align === "left"
                ? "left-4"
                : align === "right"
                ? "right-4"
                : "left-1/2 -translate-x-1/2"
            } top-0 -translate-y-1/2 rotate-45 border-4 border-transparent border-b-gray-900`}
          />
        </div>
      )}
    </div>
  );
}