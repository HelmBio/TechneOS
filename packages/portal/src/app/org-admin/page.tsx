"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  apiGet,
  type ObjectStoreBucket,
  type LLMProvider,
  type Org,
  type PaginatedResponse,
  type Team,
  type User,
} from "@/lib/api";

export default function OrgAdminOverviewPage() {
  const { user } = useAuth();
  const [org, setOrg] = useState<Org | null>(null);
  const [userCount, setUserCount] = useState(0);
  const [teamCount, setTeamCount] = useState(0);
  const [providerCount, setProviderCount] = useState(0);
  const [bucketCount, setBucketCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    if (!user?.org_id) {
      setLoading(false);
      return;
    }
    try {
      const [orgResult, usersResult, teamsResult, providersResult, bucketsResult] = await Promise.allSettled([
        apiGet<Org>(`/api/v1/orgs/${user.org_id}`),
        apiGet<PaginatedResponse<User>>("/api/v1/users", { limit: "1" }),
        apiGet<PaginatedResponse<Team>>(
          `/api/v1/orgs/${user.org_id}/teams`,
          { limit: "1" },
        ),
        apiGet<PaginatedResponse<LLMProvider>>(`/api/v1/orgs/${user.org_id}/llm-providers`, { limit: "1" }),
        apiGet<PaginatedResponse<ObjectStoreBucket>>(`/api/v1/orgs/${user.org_id}/buckets`, { limit: "1" }),
      ]);
      if (orgResult.status === "fulfilled") setOrg(orgResult.value);
      if (usersResult.status === "fulfilled") setUserCount(usersResult.value.total);
      if (teamsResult.status === "fulfilled") setTeamCount(teamsResult.value.total);
      if (providersResult.status === "fulfilled") setProviderCount(providersResult.value.total);
      if (bucketsResult.status === "fulfilled") setBucketCount(bucketsResult.value.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [user?.org_id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return <p className="text-gray-500">Loading organization info...</p>;
  }

  if (!user?.org_id) {
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-6 text-center">
        <p className="text-yellow-800">
          You are not assigned to an organization. Contact a platform
          administrator.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Org info card */}
      {org && (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-gray-900">{org.name}</h2>
          <p className="mt-1 text-sm text-gray-500">
            {org.description || "No description"}
          </p>
          <div className="mt-4 flex gap-6 text-sm">
            <div>
              <span className="text-gray-400">Slug:</span>{" "}
              <span className="font-mono text-gray-700">{org.slug}</span>
            </div>
            <div>
              <span className="text-gray-400">Status:</span>{" "}
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                  org.is_active
                    ? "bg-green-100 text-green-800"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {org.is_active ? "active" : "inactive"}
              </span>
            </div>
            <div>
              <span className="text-gray-400">Created:</span>{" "}
              <span className="text-gray-700">
                {new Date(org.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">Users</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{userCount}</p>
          <p className="mt-1 text-xs text-gray-400">Members in your organization</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">Teams</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{teamCount}</p>
          <p className="mt-1 text-xs text-gray-400">Teams within your organization</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">LLM Providers</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{providerCount}</p>
          <p className="mt-1 text-xs text-gray-400">Configured model providers</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <p className="text-sm font-medium text-gray-500">Buckets</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{bucketCount}</p>
          <p className="mt-1 text-xs text-gray-400">Registered object store buckets</p>
        </div>
      </div>
    </div>
  );
}
