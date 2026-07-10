"use client";

import Link from "next/link";
import { useCollectionCounts, type Collection } from "@/lib/use-collection-counts";
import { useLabels } from "@/lib/labels";
import type { LabelKey } from "@/lib/labels";
import {
  ToolIcon,
  TaskIcon,
  PipelineIcon,
  AgentIcon,
  AppIcon,
  DatasetIcon,
  ToolRunIcon,
  TaskRunIcon,
  PipelineRunIcon,
  AgenticRunIcon,
} from "@/components/icons";

const CARD_ICON = "h-8 w-8 text-indigo-600";

const resourceCards: {
  labelKey: LabelKey;
  href: string;
  countKey: Collection;
  icon: React.ReactNode;
}[] = [
  { labelKey: "resource.tool.plural", href: "/tools", countKey: "tools", icon: <ToolIcon className={CARD_ICON} /> },
  { labelKey: "resource.task.plural", href: "/tasks", countKey: "tasks", icon: <TaskIcon className={CARD_ICON} /> },
  { labelKey: "resource.pipeline.plural", href: "/pipelines", countKey: "pipelines", icon: <PipelineIcon className={CARD_ICON} /> },
  { labelKey: "resource.agent.plural", href: "/agents", countKey: "agents", icon: <AgentIcon className={CARD_ICON} /> },
  { labelKey: "resource.app.plural", href: "/apps", countKey: "apps", icon: <AppIcon className={CARD_ICON} /> },
  { labelKey: "resource.dataset.plural", href: "/datasets", countKey: "datasets", icon: <DatasetIcon className={CARD_ICON} /> },
];

const runCards: {
  labelKey: LabelKey;
  href: string;
  countKey?: Collection;
  icon: React.ReactNode;
}[] = [
  { labelKey: "exec.tool.plural", href: "/tool-runs", countKey: "tool-runs", icon: <ToolRunIcon className={CARD_ICON} /> },
  { labelKey: "exec.task.plural", href: "/task-runs", countKey: "task_runs", icon: <TaskRunIcon className={CARD_ICON} /> },
  { labelKey: "exec.pipeline.plural", href: "/pipeline-runs", countKey: "pipeline-runs", icon: <PipelineRunIcon className={CARD_ICON} /> },
  { labelKey: "exec.agent.plural", href: "/agentic-runs", countKey: "agentic-runs", icon: <AgenticRunIcon className={CARD_ICON} /> },
];

export default function DashboardPage() {
  const counts = useCollectionCounts();
  const { t } = useLabels();

  return (
    <div className="py-4">
      {/* Resources */}
      <section>
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">{t("section.catalog")}</h2>
        <div className="grid gap-6 grid-cols-[repeat(auto-fill,minmax(200px,1fr))]">
          {resourceCards.map((card) => {
            const count = counts[card.countKey];
            return (
              <Link
                key={card.href}
                href={card.href}
                className="group rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
              >
                <div className="mb-4 flex items-center justify-between">
                  {card.icon}
                  {count != null && (
                    <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-sm font-semibold tabular-nums text-indigo-700">
                      {count}
                    </span>
                  )}
                </div>
                <h3 className="text-sm font-semibold text-gray-900 group-hover:text-indigo-600">
                  {t(card.labelKey)}
                </h3>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Runs */}
      <section className="mt-10">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">{t("section.executions")}</h2>
        <div className="grid gap-6 grid-cols-[repeat(auto-fill,minmax(200px,1fr))]">
          {runCards.map((card) => {
            const count = card.countKey ? counts[card.countKey] : null;
            return (
              <Link
                key={card.href}
                href={card.href}
                className="group rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
              >
                <div className="mb-4 flex items-center justify-between">
                  {card.icon}
                  {count != null && (
                    <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-sm font-semibold tabular-nums text-indigo-700">
                      {count}
                    </span>
                  )}
                </div>
                <h3 className="text-sm font-semibold text-gray-900 group-hover:text-indigo-600">
                  {t(card.labelKey)}
                </h3>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}
