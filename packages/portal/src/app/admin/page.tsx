"use client";

import { useEffect, useState } from "react";
import { apiGet, type AdminStats } from "@/lib/api";

export default function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiGet<AdminStats>("/api/v1/admin/stats")
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-gray-500">Loading dashboard...</p>;
  }

  const statCategories = stats
    ? [
        { label: "Roles", total: stats.total_roles, active: null, activeLabel: "active" },
        { label: "Organizations", total: stats.total_orgs, active: stats.active_orgs, activeLabel: "active" },
        { label: "Teams", total: stats.total_teams, active: null, activeLabel: "active" },
        { label: "Users", total: stats.total_users, active: stats.active_users, activeLabel: "active" },
        { label: "LLM Providers", total: stats.total_llm_providers, active: stats.default_llm_providers, activeLabel: "default" },
        { label: "Buckets", total: stats.total_buckets, active: stats.default_buckets, activeLabel: "default" },
        { label: "Compute Backends", total: stats.total_compute_backends, active: stats.enabled_compute_backends, activeLabel: "enabled" },
        { label: "Compute Artifacts", total: stats.total_artifacts, active: null, activeLabel: "available" },
      ]
    : [];

  return (
    <div className="space-y-8">
      {/* Stats grid */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-800">
          Platform Statistics
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {statCategories.map((cat) => (
            <div
              key={cat.label}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              <p className="text-sm font-medium text-gray-500">{cat.label}</p>
              <p className="mt-2 text-3xl font-bold text-gray-900">
                {cat.total}
              </p>
              {cat.active !== null && (
                <p className="mt-1 text-xs text-gray-400">
                  {cat.active} {cat.activeLabel}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
