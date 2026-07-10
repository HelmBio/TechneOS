"use client";

import { useEffect, useState, useCallback } from "react";
import {
  apiGet,
  apiPost,
  apiDelete,
  type Subscription,
  type SubscriptionCheck,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

/** Category-level subscriptions use resource_id = "*" */
const WILDCARD = "*";

interface CategoryDef {
  resource_type: string;
  label: string;
  description: string;
}

const CATEGORIES: CategoryDef[] = [
  {
    resource_type: "dataset",
    label: "Datasets",
    description:
      "Get notified when new datasets are created or existing datasets receive new versions.",
  },
  {
    resource_type: "tool",
    label: "Tools",
    description:
      "Get notified when new tools are registered or existing tools are updated.",
  },
  {
    resource_type: "agent",
    label: "Agents",
    description:
      "Get notified when new agents are created or existing agents are updated.",
  },
  {
    resource_type: "pipeline",
    label: "Pipelines",
    description:
      "Get notified about new pipelines and pipeline status changes.",
  },
];

interface CategoryState {
  subscribed: boolean;
  subscriptionId: string | null;
  loading: boolean;
}

export default function NotificationSettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const [catState, setCatState] = useState<Record<string, CategoryState>>({});
  const [initialLoading, setInitialLoading] = useState(true);

  // Load current subscription state for each category
  useEffect(() => {
    if (authLoading || !user) return;

    const load = async () => {
      const states: Record<string, CategoryState> = {};
      await Promise.all(
        CATEGORIES.map(async (cat) => {
          try {
            const check = await apiGet<SubscriptionCheck>(
              "/api/v1/subscriptions/check",
              { resource_type: cat.resource_type, resource_id: WILDCARD }
            );
            states[cat.resource_type] = {
              subscribed: check.subscribed,
              subscriptionId: check.subscription_id,
              loading: false,
            };
          } catch {
            states[cat.resource_type] = {
              subscribed: false,
              subscriptionId: null,
              loading: false,
            };
          }
        })
      );
      setCatState(states);
      setInitialLoading(false);
    };

    load();
  }, [user, authLoading]);

  const toggle = useCallback(
    async (resourceType: string) => {
      const current = catState[resourceType];
      if (!current || current.loading) return;

      setCatState((prev) => ({
        ...prev,
        [resourceType]: { ...prev[resourceType], loading: true },
      }));

      try {
        if (current.subscribed && current.subscriptionId) {
          await apiDelete(
            `/api/v1/subscriptions/${current.subscriptionId}`
          );
          setCatState((prev) => ({
            ...prev,
            [resourceType]: {
              subscribed: false,
              subscriptionId: null,
              loading: false,
            },
          }));
        } else {
          const sub = await apiPost<Subscription>("/api/v1/subscriptions", {
            resource_type: resourceType,
            resource_id: WILDCARD,
          });
          setCatState((prev) => ({
            ...prev,
            [resourceType]: {
              subscribed: true,
              subscriptionId: sub.id,
              loading: false,
            },
          }));
        }
      } catch {
        setCatState((prev) => ({
          ...prev,
          [resourceType]: { ...prev[resourceType], loading: false },
        }));
      }
    },
    [catState]
  );

  if (authLoading)
    return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user)
    return (
      <p className="p-8 text-gray-500">
        Please{" "}
        <a href="/login" className="text-blue-600 underline">
          log in
        </a>{" "}
        to manage notification settings.
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
        <span className="text-gray-900">Notification Settings</span>
      </nav>

      <h1 className="text-2xl font-bold text-gray-900">
        Notification Settings
      </h1>
      <p className="mt-1 text-sm text-gray-500">
        Subscribe to categories to receive notifications about new resources.
        You can also follow individual resources from their detail pages.
      </p>

      <div className="mt-8 space-y-1">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
          Category Subscriptions
        </h2>

        {initialLoading ? (
          <p className="py-4 text-sm text-gray-400">Loading subscriptions...</p>
        ) : (
          <div className="mt-3 divide-y divide-gray-100 rounded-lg border border-gray-200">
            {CATEGORIES.map((cat) => {
              const state = catState[cat.resource_type] ?? {
                subscribed: false,
                subscriptionId: null,
                loading: false,
              };
              return (
                <div
                  key={cat.resource_type}
                  className="flex items-center justify-between px-5 py-4"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {cat.label}
                    </p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {cat.description}
                    </p>
                  </div>
                  <button
                    onClick={() => toggle(cat.resource_type)}
                    disabled={state.loading}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
                      state.subscribed ? "bg-blue-600" : "bg-gray-200"
                    } ${state.loading ? "opacity-50 cursor-wait" : ""}`}
                    role="switch"
                    aria-checked={state.subscribed}
                    aria-label={`Toggle ${cat.label} notifications`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out ${
                        state.subscribed ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <p className="mt-6 text-xs text-gray-400">
        Category subscriptions notify you about all new resources of that type.
        To follow a specific dataset or tool, use the Follow button on its
        detail page.
      </p>
    </div>
  );
}
