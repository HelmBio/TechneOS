import type { ReactNode } from "react";

/**
 * Shared resource / execution icons.
 *
 * Single source of truth for the glyphs used in the sidebar nav and the home
 * dashboard. Each icon takes a `className` (default `h-5 w-5`) so callers pick
 * the size and color (color via Tailwind text-* → `currentColor`).
 *
 * Definitions vs executions are a matched pair where it helps:
 *   - tools (wrench)            ↔ tool runs (play / run)
 *   - pipelines (DAG, hollow)   ↔ pipeline runs (DAG, filled)
 */

interface IconProps {
  className?: string;
}

function Glyph({ className = "h-5 w-5", children }: { className?: string; children: ReactNode }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      {children}
    </svg>
  );
}

// ── Resources ───────────────────────────────────────────────────────────

/** Function f(x) — a computational method / model / algorithm. Drawn as
 *  literal text: a prominent "f" with a smaller "(x)" argument, plain sans. */
export function ToolIcon({ className = "h-5 w-5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <text
        x="12"
        y="12"
        textAnchor="middle"
        dominantBaseline="central"
        fontWeight={600}
        fontFamily="ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
      >
        <tspan fontSize="19">f</tspan>
        <tspan fontSize="11">(x)</tspan>
      </text>
    </svg>
  );
}

export function TaskIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15a2.25 2.25 0 0 1 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25ZM6.75 12h.008v.008H6.75V12Zm0 3h.008v.008H6.75V15Zm0 3h.008v.008H6.75V18Z" />
    </Glyph>
  );
}

/** DAG: one node branching to two downstream nodes (hollow = definition). */
export function PipelineIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.1 11.1 16.9 6.9M7.1 12.9 16.9 17.1" />
      <circle cx="5" cy="12" r="2.25" />
      <circle cx="19" cy="6" r="2.25" />
      <circle cx="19" cy="18" r="2.25" />
    </Glyph>
  );
}

export function AgentIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
    </Glyph>
  );
}

export function AppIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h3a2.25 2.25 0 0 1 2.25 2.25v3A2.25 2.25 0 0 1 9 11.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h3a2.25 2.25 0 0 1 2.25 2.25v3A2.25 2.25 0 0 1 9 21H6a2.25 2.25 0 0 1-2.25-2.25v-3ZM12.75 6A2.25 2.25 0 0 1 15 3.75h3a2.25 2.25 0 0 1 2.25 2.25v3A2.25 2.25 0 0 1 18 11.25h-3A2.25 2.25 0 0 1 12.75 9V6ZM12.75 15.75A2.25 2.25 0 0 1 15 13.5h3a2.25 2.25 0 0 1 2.25 2.25v3A2.25 2.25 0 0 1 18 21h-3a2.25 2.25 0 0 1-2.25-2.25v-3Z" />
    </Glyph>
  );
}

export function DatasetIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125v-3.75" />
    </Glyph>
  );
}

// ── Executions ──────────────────────────────────────────────────────────

/** f(▶) — the function evaluated / run; the play sits in the argument slot.
 *  Pairs with the f(x) tool icon (definition → execution). */
export function ToolRunIcon({ className = "h-5 w-5" }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <text
        x="12"
        y="12"
        textAnchor="middle"
        dominantBaseline="central"
        fontWeight={600}
        fontFamily="ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
      >
        <tspan fontSize="19">f</tspan>
        <tspan fontSize="12">(</tspan>
        <tspan fontSize="9" dy="-0.5">▶</tspan>
        <tspan fontSize="12" dy="0.5">)</tspan>
      </text>
    </svg>
  );
}

export function TaskRunIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </Glyph>
  );
}

/** DAG with filled nodes = an execution of the pipeline. */
export function PipelineRunIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.1 11.1 16.9 6.9M7.1 12.9 16.9 17.1" />
      <circle cx="5" cy="12" r="2.25" fill="currentColor" stroke="none" />
      <circle cx="19" cy="6" r="2.25" fill="currentColor" stroke="none" />
      <circle cx="19" cy="18" r="2.25" fill="currentColor" stroke="none" />
    </Glyph>
  );
}

export function AgenticRunIcon({ className }: IconProps) {
  return (
    <Glyph className={className}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 0 0 2.25-2.25V6.75a2.25 2.25 0 0 0-2.25-2.25H6.75A2.25 2.25 0 0 0 4.5 6.75v10.5a2.25 2.25 0 0 0 2.25 2.25Zm.75-12h9v9h-9v-9Z" />
    </Glyph>
  );
}
