"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { apiPut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLabels } from "@/lib/labels";
import { DEFAULT_LABELS, LABEL_KEYS, type LabelKey } from "@/lib/labels";

const GROUPS: { title: string; description: string; prefix: string }[] = [
  {
    title: "Sections",
    description: "Headings that group the dashboard and sidebar.",
    prefix: "section.",
  },
  {
    title: "Catalog items",
    description: "Names for the reusable definitions in the Catalog.",
    prefix: "resource.",
  },
  {
    title: "Execution items",
    description: "Names for the run/execution records.",
    prefix: "exec.",
  },
];

export default function LabelSettingsPage() {
  const { user, loading: authLoading, role } = useAuth();
  const { overrides, refresh } = useLabels();

  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Seed the form from the current overrides whenever they load/change.
  useEffect(() => {
    setForm(overrides);
  }, [overrides]);

  const setValue = (key: LabelKey, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSavedAt(null);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    // Only persist values that differ from the default — keeps the stored
    // map minimal and lets a cleared field fall back to the default.
    const cleaned: Record<string, string> = {};
    for (const key of LABEL_KEYS) {
      const value = (form[key] ?? "").trim();
      if (value && value !== DEFAULT_LABELS[key]) {
        cleaned[key] = value;
      }
    }
    try {
      await apiPut("/api/v1/admin/labels", { overrides: cleaned });
      await refresh();
      setSavedAt(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save labels.");
    } finally {
      setSaving(false);
    }
  };

  const resetAll = () => {
    setForm({});
    setSavedAt(null);
  };

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>{" "}
        to manage label settings.
      </p>
    );
  if (role !== "platform_admin")
    return (
      <p className="p-8 text-gray-500">
        Label settings are only available to platform administrators.
      </p>
    );

  return (
    <div className="mx-auto max-w-2xl p-8">
      {/* Breadcrumb */}
      <nav className="mb-6 text-sm text-gray-500">
        <Link href="/" className="hover:text-gray-700">
          Home
        </Link>
        <span className="mx-1">/</span>
        <span className="text-gray-900">Label Settings</span>
      </nav>

      <h1 className="text-2xl font-bold text-gray-900">Label Settings</h1>
      <p className="mt-1 text-sm text-gray-500">
        Customize the names this instance uses for catalog and execution
        items. Leave a field blank to use its default. These changes affect all
        users; routes and URLs are unchanged.
      </p>

      <div className="mt-8 space-y-8">
        {GROUPS.map((group) => {
          const keys = LABEL_KEYS.filter((k) => k.startsWith(group.prefix));
          return (
            <div key={group.prefix}>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                {group.title}
              </h2>
              <p className="mt-0.5 text-xs text-gray-400">{group.description}</p>
              <div className="mt-3 divide-y divide-gray-100 rounded-lg border border-gray-200">
                {keys.map((key) => (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-4 px-5 py-3"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900">
                        {DEFAULT_LABELS[key]}
                      </p>
                      <p className="mt-0.5 truncate font-mono text-[11px] text-gray-400">
                        {key}
                      </p>
                    </div>
                    <input
                      type="text"
                      value={form[key] ?? ""}
                      placeholder={DEFAULT_LABELS[key]}
                      onChange={(e) => setValue(key, e.target.value)}
                      maxLength={100}
                      className="w-48 shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save changes"}
        </button>
        <button
          onClick={resetAll}
          disabled={saving}
          className="rounded-md border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Reset to defaults
        </button>
        {savedAt && <span className="text-sm text-green-600">Saved.</span>}
      </div>
    </div>
  );
}
