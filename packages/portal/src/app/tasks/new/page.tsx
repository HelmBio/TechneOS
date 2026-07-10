"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useLabel } from "@/lib/labels";
import { apiPost, type Tool } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { TOOL_CATEGORIES } from "@/lib/constants";

const CATEGORIES = TOOL_CATEGORIES;

interface TaskFormData {
  name: string;
  slug: string;
  description: string;
  category: string;
  tags: string;
  is_public: boolean;
  readme: string;
  assignment_type: string;
  default_assignee: string;
  due_in_hours: string;
  require_attachments: boolean;
  input_schema: string;
  output_schema: string;
  parameters_schema: string;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function CollapsibleField({
  label,
  hint,
  value,
  onChange,
  placeholder,
  rows,
  language,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows: number;
  language: "markdown" | "json";
}) {
  const [open, setOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onChange((reader.result as string) || "");
    reader.readAsText(file);
    e.target.value = "";
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => e.key === "Enter" && setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <svg className={`h-4 w-4 text-gray-400 transition-transform ${open ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
          <span>{label}</span>
          {value && <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">{(value.length > 40 ? value.slice(0, 40) + "…" : value)}</span>}
          {hint && <span className="text-xs text-gray-400 font-normal">{hint}</span>}
        </div>
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <input ref={fileRef} type="file" accept={language === "json" ? ".json" : ".md,.markdown,.txt"} onChange={handleFile} className="hidden" />
          <button type="button" onClick={() => fileRef.current?.click()}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
          >Upload {language === "json" ? "JSON" : "Markdown"}</button>
        </div>
      </div>
      {open && (
        <div className="border-t border-gray-200 px-4 py-3">
          <textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            rows={rows}
            placeholder={placeholder}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      )}
    </div>
  );
}

export default function NewTaskPage() {
  const tasksLabel = useLabel("resource.task.plural");
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slugManual, setSlugManual] = useState(false);

  const [task, setTask] = useState<TaskFormData>({
    name: "",
    slug: "",
    description: "",
    category: "general",
    tags: "",
    is_public: false,
    readme: "",
    assignment_type: "user",
    default_assignee: "",
    due_in_hours: "72",
    require_attachments: false,
    input_schema: "",
    output_schema: "",
    parameters_schema: "",
  });

  const handleNameChange = (name: string) => {
    setTask((prev) => ({
      ...prev,
      name,
      slug: slugManual ? prev.slug : slugify(name),
    }));
  };

  const handleSubmit = async () => {
    setError(null);
    setSaving(true);
    try {
      const tags = task.tags.split(",").map((t) => t.trim()).filter(Boolean);
      const parseJson = (s: string) => {
        const trimmed = s.trim();
        return trimmed ? JSON.parse(trimmed) : {};
      };
      const created = await apiPost<Tool>("/api/v1/tools", {
        name: task.name,
        slug: task.slug,
        description: task.description || null,
        category: task.category,
        tool_type: "human",
        tags,
        is_public: task.is_public,
        readme: task.readme || null,
        assignment_type: task.assignment_type,
        default_assignee: task.default_assignee || null,
        due_in_hours: task.due_in_hours ? Number(task.due_in_hours) : null,
        require_attachments: task.require_attachments,
        input_schema: parseJson(task.input_schema),
        output_schema: parseJson(task.output_schema),
        parameters_schema: parseJson(task.parameters_schema),
      });
      router.push(`/tasks/${created.id}`);
    } catch (err: unknown) {
      const msg = err instanceof SyntaxError ? "Invalid JSON in schema field" : err instanceof Error ? err.message : "Failed to save task";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  if (authLoading) return <p className="p-8 text-gray-500">Loading...</p>;
  if (!user) return <p className="p-8 text-gray-500">Please <a href="/login" className="text-blue-600 underline">log in</a> to manage tasks.</p>;

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/tasks" className="hover:text-blue-600">{tasksLabel}</Link>
        <span>/</span>
        <span>New Task</span>
      </div>

      <h1 className="text-2xl font-bold text-gray-900">Define New Task</h1>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm space-y-4">
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
          <input type="text" value={task.name} onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g. Compound Review"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Slug */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Slug *</label>
          <div className="flex items-center gap-2">
            <input type="text" value={task.slug} onChange={(e) => { setSlugManual(true); setTask((prev) => ({ ...prev, slug: e.target.value })); }}
              placeholder="e.g. compound-review"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            {slugManual && (
              <button type="button" onClick={() => { setSlugManual(false); setTask((prev) => ({ ...prev, slug: slugify(prev.name) })); }}
                className="whitespace-nowrap text-xs text-blue-600 hover:underline">Auto</button>
            )}
          </div>
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <textarea value={task.description} onChange={(e) => setTask((prev) => ({ ...prev, description: e.target.value }))}
            placeholder="Describe what this task involves..."
            rows={3}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Category + Assignment Type */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
            <select value={task.category} onChange={(e) => setTask((prev) => ({ ...prev, category: e.target.value }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500">
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Assignment Type</label>
            <select value={task.assignment_type} onChange={(e) => setTask((prev) => ({ ...prev, assignment_type: e.target.value }))}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500">
              <option value="user">User</option>
              <option value="team">Team</option>
            </select>
          </div>
        </div>

        {/* Default Assignee */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Default Assignee</label>
          <input type="text" value={task.default_assignee} onChange={(e) => setTask((prev) => ({ ...prev, default_assignee: e.target.value }))}
            placeholder={task.assignment_type === "user" ? "User ID" : "Team slug"}
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Due In + Require Attachments */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Due In (hours)</label>
            <input type="number" value={task.due_in_hours} onChange={(e) => setTask((prev) => ({ ...prev, due_in_hours: e.target.value }))}
              min={1}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-end pb-2">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={task.require_attachments} onChange={(e) => setTask((prev) => ({ ...prev, require_attachments: e.target.checked }))}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              Require file attachments on submission
            </label>
          </div>
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Tags</label>
          <input type="text" value={task.tags} onChange={(e) => setTask((prev) => ({ ...prev, tags: e.target.value }))}
            placeholder="comma-separated, e.g. review, approval, synthesis"
            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </section>

      <div className="space-y-3">
        <CollapsibleField
          label="Task Documentation (README)"
          hint="— why this task exists, SOPs, workflow context"
          value={task.readme}
          onChange={(v) => setTask((prev) => ({ ...prev, readme: v }))}
          placeholder="# My Task&#10;&#10;What it involves, how to complete it, expected outputs..."
          rows={8}
          language="markdown"
        />
        <CollapsibleField
          label="Input Schema"
          hint="— defines data the task expects from upstream steps"
          value={task.input_schema}
          onChange={(v) => setTask((prev) => ({ ...prev, input_schema: v }))}
          placeholder='{"smiles": {"type": "string", "description": "SMILES string"}}'
          rows={5}
          language="json"
        />
        <CollapsibleField
          label="Output Schema"
          hint="— defines data the task produces for downstream steps"
          value={task.output_schema}
          onChange={(v) => setTask((prev) => ({ ...prev, output_schema: v }))}
          placeholder='{"approved": {"type": "boolean"}}'
          rows={5}
          language="json"
        />
        <CollapsibleField
          label="Parameters Schema"
          hint="— runtime configuration parameters"
          value={task.parameters_schema}
          onChange={(v) => setTask((prev) => ({ ...prev, parameters_schema: v }))}
          placeholder='{"priority": {"type": "string", "enum": ["low", "high"]}}'
          rows={5}
          language="json"
        />
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={task.is_public} onChange={(e) => setTask((prev) => ({ ...prev, is_public: e.target.checked }))}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        Public task (visible to all organizations)
      </label>

      <div className="flex items-center gap-3">
        <button onClick={handleSubmit} disabled={saving || !task.name || !task.slug}
          className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed">
          {saving ? "Saving..." : "Create Task"}
        </button>
        <Link href="/tasks" className="rounded-md border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</Link>
      </div>
    </div>
  );
}
