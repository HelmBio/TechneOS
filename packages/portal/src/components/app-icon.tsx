"use client";

import { useState } from "react";
import { API_BASE } from "@/lib/api";

interface AppIconProps {
  iconUrl: string | null;
  name: string;
}

export function AppIcon({ iconUrl, name }: AppIconProps) {
  const [failed, setFailed] = useState(false);

  if (iconUrl && !failed) {
    const src = iconUrl.startsWith("/") ? `${API_BASE}${iconUrl}` : iconUrl;
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt=""
        className="h-10 w-10 rounded-md object-cover"
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <div className="flex h-10 w-10 items-center justify-center rounded-md bg-indigo-50 text-indigo-600">
      <span className="text-sm font-semibold">{name.charAt(0)}</span>
    </div>
  );
}
