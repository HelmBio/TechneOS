"use client";

import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  type Node,
  type Edge,
  type NodeProps,
  Position,
  Background,
  Controls,
  Handle,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import type { PipelineStepConfig } from "@/lib/api";

/* ── Status styling ─────────────────────────────────────── */

const STATUS_BORDER: Record<string, string> = {
  pending: "border-gray-300",
  queued: "border-blue-300",
  running: "border-blue-500",
  completed: "border-green-500",
  failed: "border-red-500",
  cancelled: "border-gray-400",
  skipped: "border-gray-300",
  retrying: "border-orange-500",
};

const STATUS_BG: Record<string, string> = {
  pending: "bg-white",
  queued: "bg-blue-50",
  running: "bg-blue-50",
  completed: "bg-green-50",
  failed: "bg-red-50",
  cancelled: "bg-gray-50",
  skipped: "bg-gray-50",
  retrying: "bg-orange-50",
};

const STATUS_DOT: Record<string, string> = {
  pending: "bg-gray-400",
  queued: "bg-blue-400",
  running: "bg-blue-500 animate-pulse",
  completed: "bg-green-500",
  failed: "bg-red-500",
  cancelled: "bg-gray-400",
  skipped: "bg-gray-300",
  retrying: "bg-orange-500 animate-pulse",
};

/* ── Types ──────────────────────────────────────────────── */

export interface StepStatus {
  step_name: string;
  status: string;
}

interface StepNodeData {
  label: string;
  toolSlug: string;
  toolVersion: number | null;
  status: string | null;
  [key: string]: unknown;
}

type StepNode = Node<StepNodeData>;

/* ── Custom node ────────────────────────────────────────── */

function StepNodeComponent({ data }: NodeProps<StepNode>) {
  const status = data.status ?? "pending";
  const borderClass = STATUS_BORDER[status] ?? "border-gray-300";
  const bgClass = STATUS_BG[status] ?? "bg-white";
  const dotClass = STATUS_DOT[status] ?? "bg-gray-400";

  return (
    <div
      className={`group relative rounded-lg border-2 ${borderClass} ${bgClass} px-4 py-3 shadow-sm min-w-[180px]`}
    >
      <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 top-full mt-1 z-10 hidden group-hover:block rounded bg-gray-800 px-2 py-1 text-xs text-white capitalize max-w-[200px] w-max">
        {status}
      </span>
      <Handle type="target" position={Position.Left} className="!bg-gray-400 !w-2 !h-2" />
      <div className="flex items-center gap-2 mb-1">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotClass}`} />
        <span className="font-medium text-sm text-gray-900 truncate">{data.label}</span>
      </div>
      <span className="text-xs font-mono text-gray-500">
        {data.toolSlug}
        {data.toolVersion != null ? `:v${data.toolVersion}` : ""}
      </span>
      <Handle type="source" position={Position.Right} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}

const nodeTypes = { step: StepNodeComponent };

/* ── Dagre layout ───────────────────────────────────────── */

const NODE_WIDTH = 220;
const NODE_HEIGHT = 70;

function layoutGraph(
  steps: PipelineStepConfig[],
  statuses: Map<string, string> | null,
): { nodes: StepNode[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", ranksep: 80, nodesep: 40 });

  for (const step of steps) {
    g.setNode(step.name, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  const edges: Edge[] = [];
  for (const step of steps) {
    for (const dep of step.depends_on) {
      const edgeId = `${dep}->${step.name}`;
      g.setEdge(dep, step.name);
      edges.push({
        id: edgeId,
        source: dep,
        target: step.name,
        style: { stroke: "#94a3b8", strokeWidth: 2 },
        animated: statuses?.get(step.name) === "running",
      });
    }
  }

  dagre.layout(g);

  const nodes: StepNode[] = steps.map((step) => {
    const pos = g.node(step.name);
    return {
      id: step.name,
      type: "step",
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: {
        label: step.name,
        toolSlug: step.tool_slug,
        toolVersion: step.tool_version,
        status: statuses?.get(step.name) ?? null,
      },
    };
  });

  return { nodes, edges };
}

/* ── Component ──────────────────────────────────────────── */

export interface PipelineGraphProps {
  steps: PipelineStepConfig[];
  /** Optional step statuses for run views (step_name -> status) */
  stepStatuses?: StepStatus[];
  /** Height of the graph container (default "320px") */
  height?: string;
  /** Called when a step node is clicked */
  onStepClick?: (stepName: string) => void;
}

export default function PipelineGraph({
  steps,
  stepStatuses,
  height = "320px",
  onStepClick,
}: PipelineGraphProps) {
  const statusMap = useMemo(() => {
    if (!stepStatuses || stepStatuses.length === 0) return null;
    return new Map(stepStatuses.map((s) => [s.step_name, s.status]));
  }, [stepStatuses]);

  const { nodes, edges } = useMemo(
    () => layoutGraph(steps, statusMap),
    [steps, statusMap],
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onStepClick?.(node.id);
    },
    [onStepClick],
  );

  if (steps.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-500" style={{ height }}>
        No steps defined
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
      >
        <Background gap={16} size={1} color="#e5e7eb" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
