"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { useParams } from "next/navigation";
import { apiGet, apiPost, type AppLaunchResult, type AppRecord } from "@/lib/api";

export default function EmbeddedLaunchPage() {
  const appsLabel = useLabel("resource.app.plural");
  const params = useParams<{ id: string }>();
  const [app, setApp] = useState<AppRecord | null>(null);
  const [result, setResult] = useState<AppLaunchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params.id) return;
    let cancelled = false;
    (async () => {
      try {
        const a = await apiGet<AppRecord>(`/api/v1/apps/${params.id}`);
        if (cancelled) return;
        setApp(a);
        const r = await apiPost<AppLaunchResult>(`/api/v1/apps/${a.id}/launch`, {});
        if (cancelled) return;
        setResult(r);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  if (error) {
    return (
      <div className="p-8">
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!app || !result) {
    return <p className="p-8 text-gray-500">Starting…</p>;
  }

  // Hand off the optional launch token via postMessage once the iframe is ready.
  // Same-origin so we can target window.location.origin.
  const onLoad = (e: React.SyntheticEvent<HTMLIFrameElement>) => {
    const target = e.currentTarget.contentWindow;
    if (!target) return;
    target.postMessage({ type: "ping" }, window.location.origin);
    if (result.token) {
      target.postMessage(
        { type: "launch_token", token: result.token, expires_at: result.expires_at },
        window.location.origin,
      );
    }
  };

  return (
    <div className="flex h-[calc(100vh-5.5rem)] flex-col gap-3">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/apps" className="hover:text-blue-600">{appsLabel}</Link>
        <span>/</span>
        <span>{app.slug}</span>
      </div>
      <iframe
        src={result.launch_url}
        title={app.name}
        sandbox={app.embed_sandbox || undefined}
        allow={app.embed_allow || undefined}
        className="w-full flex-1 rounded-lg border border-gray-200 bg-white"
        onLoad={onLoad}
      />
    </div>
  );
}
