import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PipelineGraph from "@/components/pipeline-graph";
import type { PipelineStepConfig } from "@/lib/api";

// Mock ReactFlow since it requires a browser resize observer
vi.mock("@xyflow/react", () => {
  const Handle = ({ type }: { type: string }) => (
    <div data-testid={`handle-${type}`} />
  );
  const Background = () => <div data-testid="rf-background" />;
  const Controls = () => <div data-testid="rf-controls" />;
  const ReactFlow = ({
    nodes,
    edges,
    nodeTypes,
    onNodeClick,
  }: {
    nodes: Array<{ id: string; data: Record<string, unknown> }>;
    edges: Array<{ id: string }>;
    nodeTypes: Record<string, React.FC<{ data: Record<string, unknown> }>>;
    onNodeClick?: (event: React.MouseEvent, node: { id: string }) => void;
  }) => {
    const StepNode = nodeTypes.step;
    return (
      <div data-testid="react-flow">
        {nodes.map((node) => (
          <div
            key={node.id}
            data-testid={`node-${node.id}`}
            onClick={(e) => onNodeClick?.(e, node as { id: string })}
          >
            <StepNode data={node.data} />
          </div>
        ))}
        {edges.map((edge) => (
          <div key={edge.id} data-testid={`edge-${edge.id}`} />
        ))}
      </div>
    );
  };
  return {
    ReactFlow,
    Background,
    Controls,
    Handle,
    Position: { Left: "left", Right: "right" },
  };
});

// Mock dagre
vi.mock("@dagrejs/dagre", () => {
  class MockGraph {
    setDefaultEdgeLabel() {}
    setGraph() {}
    setNode() {}
    setEdge() {}
    node() {
      return { x: 100, y: 50 };
    }
  }
  return {
    default: {
      graphlib: { Graph: MockGraph },
      layout: vi.fn(),
    },
  };
});

const sampleSteps: PipelineStepConfig[] = [
  {
    name: "prep",
    tool_slug: "rdkit",
    tool_version: 1,
    parameters: { pH: 7.4 },
    depends_on: [],
  },
  {
    name: "dock",
    tool_slug: "autodock",
    tool_version: 2,
    parameters: {},
    depends_on: ["prep"],
  },
];

describe("PipelineGraph", () => {
  it("renders empty state when no steps", () => {
    render(<PipelineGraph steps={[]} />);
    expect(screen.getByText("No steps defined")).toBeInTheDocument();
  });

  it("renders nodes for each step", () => {
    render(<PipelineGraph steps={sampleSteps} />);
    expect(screen.getByTestId("node-prep")).toBeInTheDocument();
    expect(screen.getByTestId("node-dock")).toBeInTheDocument();
  });

  it("renders edges for dependencies", () => {
    render(<PipelineGraph steps={sampleSteps} />);
    expect(screen.getByTestId("edge-prep->dock")).toBeInTheDocument();
  });

  it("displays step names and tool slugs", () => {
    render(<PipelineGraph steps={sampleSteps} />);
    expect(screen.getByText("prep")).toBeInTheDocument();
    expect(screen.getByText("rdkit:v1")).toBeInTheDocument();
    expect(screen.getByText("dock")).toBeInTheDocument();
    expect(screen.getByText("autodock:v2")).toBeInTheDocument();
  });

  it("calls onStepClick when a node is clicked", () => {
    const handleClick = vi.fn();
    render(<PipelineGraph steps={sampleSteps} onStepClick={handleClick} />);
    fireEvent.click(screen.getByTestId("node-prep"));
    expect(handleClick).toHaveBeenCalledWith("prep");
  });

  it("renders with step statuses", () => {
    const statuses = [
      { step_name: "prep", status: "completed" },
      { step_name: "dock", status: "running" },
    ];
    render(<PipelineGraph steps={sampleSteps} stepStatuses={statuses} />);
    // Component should still render nodes
    expect(screen.getByTestId("node-prep")).toBeInTheDocument();
    expect(screen.getByTestId("node-dock")).toBeInTheDocument();
  });

  it("uses custom height", () => {
    const { container } = render(
      <PipelineGraph steps={sampleSteps} height="500px" />
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.style.height).toBe("500px");
  });
});
