export const RUN_STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  queued: "bg-blue-100 text-blue-800",
  running: "bg-blue-100 text-blue-800",
  accepted: "bg-blue-100 text-blue-800",
  in_progress: "bg-indigo-100 text-indigo-800",
  "in progress": "bg-indigo-100 text-indigo-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  declined: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-800",
  skipped: "bg-gray-100 text-gray-500",
  escalated: "bg-orange-100 text-orange-800",
  retrying: "bg-orange-100 text-orange-800",
};

export function isActive(status: string): boolean {
  return ["pending", "queued", "running", "accepted", "in_progress", "retrying"].includes(status);
}

export function isTerminal(status: string): boolean {
  return ["completed", "failed", "cancelled", "declined"].includes(status);
}

export function formatDuration(start: string | null, end: string | null, status?: string): string {
  if (!start) return "—";
  const s = new Date(start).getTime();
  const e = end
    ? new Date(end).getTime()
    : status && isActive(status)
      ? Date.now()
      : null;
  if (e == null) return "—";
  const secs = Math.round((e - s) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m ${secs % 60}s`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export const RUN_STATUS_ICONS: Record<string, string> = {
  pending: "○",
  queued: "○",
  running: "◎",
  completed: "✓",
  failed: "✗",
  cancelled: "—",
  skipped: "—",
  retrying: "↻",
};

// ── Run-tree grouping (restart chains) ───────────────────────────

interface RestartableRun {
  id: string;
  restarted_from: string | null;
  created_at: string;
}

export function buildRunTree<T extends RestartableRun>(
  runs: T[],
  ancestors: Map<string, T>,
): { parent: T; children: T[] }[] {
  const byId = new Map(runs.map((r) => [r.id, r]));
  for (const [id, r] of ancestors) {
    if (!byId.has(id)) byId.set(id, r);
  }

  const nested = new Set<string>();
  const childrenMap = new Map<string, T[]>();
  for (const r of byId.values()) {
    if (r.restarted_from && byId.has(r.restarted_from)) {
      nested.add(r.id);
      const list = childrenMap.get(r.restarted_from) || [];
      list.push(r);
      childrenMap.set(r.restarted_from, list);
    }
  }

  const rootChildren = new Map<string, T[]>();
  function getRoot(id: string): string {
    const run = byId.get(id);
    if (run?.restarted_from && byId.has(run.restarted_from)) {
      return getRoot(run.restarted_from);
    }
    return id;
  }

  for (const [parentId, children] of childrenMap) {
    const root = getRoot(parentId);
    const existing = rootChildren.get(root) || [];
    if (parentId !== root && !existing.some((r) => r.id === parentId)) {
      const intermediate = byId.get(parentId);
      if (intermediate) existing.push(intermediate);
    }
    const existingIds = new Set(existing.map((r) => r.id));
    for (const child of children) {
      if (!existingIds.has(child.id)) {
        existing.push(child);
        existingIds.add(child.id);
      }
    }
    rootChildren.set(root, existing);
  }

  const pageIds = new Set(runs.map((r) => r.id));
  const result: { parent: T; children: T[] }[] = [];
  for (const [rootId] of rootChildren) {
    if (nested.has(rootId)) continue;
    const parent = byId.get(rootId);
    if (!parent) continue;
    const children = rootChildren.get(rootId) || [];
    const groupHasPageRun = pageIds.has(parent.id) || children.some((c) => pageIds.has(c.id));
    if (!groupHasPageRun) continue;
    children.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    result.push({ parent, children });
  }
  for (const r of runs) {
    if (nested.has(r.id)) continue;
    if (result.some((g) => g.parent.id === r.id)) continue;
    result.push({ parent: r, children: [] });
  }
  result.sort((a, b) => {
    const latestA = a.children.length > 0
      ? new Date(a.children[a.children.length - 1].created_at).getTime()
      : new Date(a.parent.created_at).getTime();
    const latestB = b.children.length > 0
      ? new Date(b.children[b.children.length - 1].created_at).getTime()
      : new Date(b.parent.created_at).getTime();
    return latestB - latestA;
  });
  return result;
}

// ── Pagination helper ────────────────────────────────────────────

export function buildPageNumbers(current: number, total: number): (number | "...")[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const pages: (number | "...")[] = [];
  const addPage = (p: number) => {
    if (p >= 1 && p <= total && !pages.includes(p)) pages.push(p);
  };

  addPage(1);
  if (current > 3) pages.push("...");
  for (let i = current - 1; i <= current + 1; i++) addPage(i);
  if (current < total - 2) pages.push("...");
  addPage(total);

  return pages;
}

// ── File download helper ─────────────────────────────────────────

export async function downloadFile(url: string, filename: string): Promise<void> {
  const resp = await fetch(url);
  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
