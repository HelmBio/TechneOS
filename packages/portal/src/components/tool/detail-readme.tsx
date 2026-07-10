"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { CollapsibleSection } from "@/components/collapsible-section";

interface DetailReadmeProps {
  readme: string | null;
  name: string;
  /** Render the section even when there is no README yet (shows a placeholder). */
  showWhenEmpty?: boolean;
}

export function DetailReadme({ readme, name, showWhenEmpty = false }: DetailReadmeProps) {
  if (!readme && !showWhenEmpty) return null;

  if (!readme) {
    return (
      <CollapsibleSection title="README" defaultOpen={false}>
        <p className="text-sm text-gray-500 italic">No README yet.</p>
      </CollapsibleSection>
    );
  }

  const openInPopup = () => {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="utf-8" />
        <title>${name} - README</title>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"><\/script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css" />
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem; line-height: 1.6; }
          pre { background: #f6f8fa; padding: 1rem; border-radius: 6px; overflow-x: auto; }
          code { font-family: "SF Mono", Monaco, "Cascadia Code", monospace; }
          @media print { .no-print { display: none !important; } }
        </style>
      </head>
      <body>
        <div class="no-print" style="margin-bottom:1rem;">
          <button onclick="window.print()" style="padding:0.5rem 1rem;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:0.875rem;">
            Download as PDF
          </button>
        </div>
        <div id="content" class="markdown-preview"></div>
        <script>
          document.getElementById("content").innerHTML = marked.parse(${JSON.stringify(readme)});
        <\/script>
      </body>
      </html>
    `);
    w.document.close();
  };

  return (
    <CollapsibleSection
      title="README"
      defaultOpen={false}
      after={
        <span
          onClick={(e) => { e.stopPropagation(); openInPopup(); }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); openInPopup(); } }}
          title="Open README in new window"
          className="rounded p-1 text-gray-400 hover:text-gray-600 cursor-pointer"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </span>
      }
    >
      <div className="markdown-preview">
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
          {readme}
        </ReactMarkdown>
      </div>
    </CollapsibleSection>
  );
}
