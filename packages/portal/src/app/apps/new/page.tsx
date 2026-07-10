"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost, type AppRecord } from "@/lib/api";

type LaunchMode = "external" | "embedded";
type AuthMode = "none" | "oidc" | "signed_jwt";

export default function NewAppPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("general");
  const [tags, setTags] = useState("");
  const [iconUrl, setIconUrl] = useState("");
  const [launchMode, setLaunchMode] = useState<LaunchMode>("external");

  // external
  const [externalUrl, setExternalUrl] = useState("");

  // embedded
  const [dockerImage, setDockerImage] = useState("");
  const [dockerTag, setDockerTag] = useState("latest");
  const [containerPort, setContainerPort] = useState<number | "">("");
  const [healthCheckPath, setHealthCheckPath] = useState("/");
  const [embedSandbox, setEmbedSandbox] = useState("allow-scripts allow-same-origin");
  const [embedAllow, setEmbedAllow] = useState("");

  // auth
  const [authMode, setAuthMode] = useState<AuthMode>("none");
  const [oidcClientId, setOidcClientId] = useState("");
  const [launchAud, setLaunchAud] = useState("");

  const [isPublic, setIsPublic] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const payload: Record<string, unknown> = {
      name,
      slug,
      description: description || null,
      category,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      icon_url: iconUrl || null,
      launch_mode: launchMode,
      auth_mode: authMode,
      is_public: isPublic,
    };
    if (launchMode === "external") {
      payload.external_url = externalUrl;
    } else {
      payload.docker_image = dockerImage;
      payload.docker_tag = dockerTag;
      payload.container_port = Number(containerPort);
      payload.health_check_path = healthCheckPath;
      payload.embed_sandbox = embedSandbox || null;
      payload.embed_allow = embedAllow || null;
    }
    if (authMode === "oidc") payload.oidc_client_id = oidcClientId;
    if (authMode === "signed_jwt") payload.launch_token_audience = launchAud;
    try {
      const created = await apiPost<AppRecord>("/api/v1/apps", payload);
      router.push(`/apps/${created.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900">New App</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field label="Name">
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Slug (URL-safe)">
          <input
            className={inputCls}
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, ""))}
            pattern="^[a-z0-9][a-z0-9._-]*$"
            required
          />
        </Field>
        <Field label="Description">
          <textarea
            className={inputCls}
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Category">
            <select className={inputCls} value={category} onChange={(e) => setCategory(e.target.value)}>
              {["visualization", "notebook", "editor", "data-browser", "ml-playground", "general"].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Tags (comma-separated)">
            <input className={inputCls} value={tags} onChange={(e) => setTags(e.target.value)} />
          </Field>
        </div>
        <Field label="Icon URL (optional)">
          <input className={inputCls} value={iconUrl} onChange={(e) => setIconUrl(e.target.value)} />
        </Field>

        <fieldset className="rounded-md border border-gray-200 p-4">
          <legend className="px-2 text-sm font-medium text-gray-700">Launch mode</legend>
          <div className="flex gap-4">
            {(["external", "embedded"] as LaunchMode[]).map((m) => (
              <label key={m} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="launch_mode"
                  value={m}
                  checked={launchMode === m}
                  onChange={() => setLaunchMode(m)}
                />
                {m}
              </label>
            ))}
          </div>

          {launchMode === "external" ? (
            <Field label="External URL" className="mt-3">
              <input
                className={inputCls}
                type="url"
                value={externalUrl}
                onChange={(e) => setExternalUrl(e.target.value)}
                required
              />
            </Field>
          ) : (
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <Field label="Docker image" className="col-span-2">
                  <input
                    className={inputCls}
                    value={dockerImage}
                    onChange={(e) => setDockerImage(e.target.value)}
                    required
                  />
                </Field>
                <Field label="Tag">
                  <input className={inputCls} value={dockerTag} onChange={(e) => setDockerTag(e.target.value)} />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Container port">
                  <input
                    className={inputCls}
                    type="number"
                    value={containerPort}
                    onChange={(e) =>
                      setContainerPort(e.target.value === "" ? "" : Number(e.target.value))
                    }
                    required
                  />
                </Field>
                <Field label="Health check path">
                  <input
                    className={inputCls}
                    value={healthCheckPath}
                    onChange={(e) => setHealthCheckPath(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="iframe sandbox flags">
                <input className={inputCls} value={embedSandbox} onChange={(e) => setEmbedSandbox(e.target.value)} />
              </Field>
              <Field label="iframe allow directives">
                <input className={inputCls} value={embedAllow} onChange={(e) => setEmbedAllow(e.target.value)} />
              </Field>
            </div>
          )}
        </fieldset>

        <fieldset className="rounded-md border border-gray-200 p-4">
          <legend className="px-2 text-sm font-medium text-gray-700">Auth handoff</legend>
          <select className={inputCls} value={authMode} onChange={(e) => setAuthMode(e.target.value as AuthMode)}>
            <option value="none">none — app handles its own auth</option>
            <option value="oidc">oidc — Keycloak SSO client</option>
            <option value="signed_jwt">signed_jwt — platform mints a token</option>
          </select>
          {authMode === "oidc" && (
            <Field label="OIDC client_id" className="mt-3">
              <input className={inputCls} value={oidcClientId} onChange={(e) => setOidcClientId(e.target.value)} required />
            </Field>
          )}
          {authMode === "signed_jwt" && (
            <Field label="Launch token audience" className="mt-3">
              <input className={inputCls} value={launchAud} onChange={(e) => setLaunchAud(e.target.value)} required />
            </Field>
          )}
        </fieldset>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
          Public (visible across orgs)
        </label>

        {error && (
          <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Create
          </button>
          <button
            type="button"
            onClick={() => router.push("/apps")}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

const inputCls =
  "block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`block ${className || ""}`}>
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      {children}
    </label>
  );
}
