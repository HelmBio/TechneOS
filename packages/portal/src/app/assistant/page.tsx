"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuth } from "@/lib/auth";
import { apiDelete, apiGet, apiPatch, ssePost, type ChatMessage, type Conversation, type ConversationDetail, type PaginatedResponse } from "@/lib/api";

export default function AssistantPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || streaming) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);

    const assistantMsg: ChatMessage = {
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
      tool_calls: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const body: Record<string, unknown> = {
        message: userMsg.content,
      };
      if (conversationId) body.conversation_id = conversationId;

      const resp = await ssePost("/api/v1/assistant/chat", body);

      if (!resp.ok) {
        const errText = await resp.text();
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = { ...updated[updated.length - 1], content: `Error: ${resp.status} ${errText}` };
          return updated;
        });
        setStreaming(false);
        return;
      }

      const reader = resp.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const parsed = JSON.parse(line.slice(6));
            if (parsed.type === "run_started" && parsed.conversation_id) {
              setConversationId(parsed.conversation_id);
            } else if (parsed.type === "token") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = { ...last, content: last.content + (parsed.text || "") };
                return updated;
              });
            } else if (parsed.type === "tool_call") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = {
                  ...last,
                  tool_calls: [...(last.tool_calls || []), { name: parsed.name, args: parsed.args || {} }],
                };
                return updated;
              });
            } else if (parsed.type === "tool_result") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                const resultStr = typeof parsed.result === "string" ? parsed.result : JSON.stringify(parsed.result);
                updated[updated.length - 1] = {
                  ...last,
                  tool_results: [...(last.tool_results || []), { name: parsed.name, result: resultStr }],
                };
                return updated;
              });
            } else if (parsed.type === "delegation_started") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = {
                  ...last,
                  delegation: { agent_id: parsed.agent_id, task: parsed.task, status: "running" },
                };
                return updated;
              });
            } else if (parsed.type === "delegation_completed") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = {
                  ...last,
                  delegation: { ...last.delegation!, result: parsed.result, status: "completed" },
                };
                return updated;
              });
            } else if (parsed.type === "error") {
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = { ...updated[updated.length - 1], content: `Error: ${parsed.message}` };
                return updated;
              });
            }
          } catch { /* skip */ }
        }
      }
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = { ...updated[updated.length - 1], content: `Connection error: ${err}` };
        return updated;
      });
    } finally {
      setStreaming(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const startNewRun = () => {
    setMessages([]);
    setConversationId(null);
    setHistoryOpen(false);
  };

  const fetchConversations = async () => {
    setLoadingHistory(true);
    try {
      const resp = await apiGet<PaginatedResponse<Conversation>>("/api/v1/agentic-runs", { limit: "50" });
      setConversations(resp.items);
    } catch {
      setConversations([]);
    } finally {
      setLoadingHistory(false);
    }
  };

  const toggleHistory = () => {
    const next = !historyOpen;
    setHistoryOpen(next);
    if (next) fetchConversations();
  };

  const loadConversation = async (conv: Conversation) => {
    try {
      const detail = await apiGet<ConversationDetail>(`/api/v1/agentic-runs/${conv.id}`);
      const loaded: ChatMessage[] = [];
      for (const run of detail.tasks) {
        loaded.push({ role: "user", content: run.task, timestamp: run.created_at });
        if (run.result) {
          let content: string;
          const res = run.result as Record<string, unknown>;
          if (typeof res.response === "string") {
            content = res.response;
          } else if (typeof res.output === "string") {
            content = res.output;
          } else {
            content = "```json\n" + JSON.stringify(run.result, null, 2) + "\n```";
          }
          loaded.push({ role: "assistant", content, timestamp: run.updated_at });
        }
      }
      setMessages(loaded);
      setConversationId(conv.id);
      setHistoryOpen(false);
    } catch { /* ignore */ }
  };

  const deleteConversation = async (e: React.MouseEvent, conv: Conversation) => {
    e.stopPropagation();
    if (confirmDeleteId !== conv.id) {
      setConfirmDeleteId(conv.id);
      return;
    }
    setConfirmDeleteId(null);
    try {
      await apiDelete(`/api/v1/agentic-runs/${conv.id}`);
      setConversations((prev) => prev.filter((c) => c.id !== conv.id));
      if (conversationId === conv.id) {
        setMessages([]);
        setConversationId(null);
      }
    } catch { /* ignore */ }
  };

  const startEditing = (e: React.MouseEvent, conv: Conversation) => {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title || "");
    setConfirmDeleteId(null);
  };

  const saveTitle = async (e: React.FormEvent | React.FocusEvent, convId: string) => {
    e.stopPropagation();
    if ("preventDefault" in e) e.preventDefault();
    const trimmed = editTitle.trim();
    if (trimmed) {
      try {
        const updated = await apiPatch<Conversation>(`/api/v1/agentic-runs/${convId}`, { title: trimmed });
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, title: updated.title } : c)));
      } catch { /* ignore */ }
    }
    setEditingId(null);
  };

  if (!user) {
    return <p className="py-12 text-center text-gray-500">Please log in to use the Platform Assistant.</p>;
  }

  return (
    <div className="-mx-4 -my-3 flex h-[calc(100vh-3.5rem)] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Platform Assistant</h1>
          <p className="text-sm text-gray-500">
            I am ready to help you explore datasets, tools, pipelines, apps, and agents on the platform. Just ask me anything!
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleHistory}
            className={`rounded-lg border p-2 transition ${
              historyOpen ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-gray-300 text-gray-700 hover:bg-gray-50"
            }`}
            title="Run history"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
            </svg>
          </button>
          <button
            onClick={startNewRun}
            className="rounded-lg border border-gray-300 p-2 text-gray-700 hover:bg-gray-50"
            title="New run"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex flex-1 overflow-hidden">
        {/* History panel */}
        {historyOpen && (
          <div className="flex w-72 shrink-0 flex-col border-r border-gray-200 bg-gray-50">
            <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-gray-700">History</h2>
              <button
                onClick={() => setHistoryOpen(false)}
                className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
                title="Close history"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {loadingHistory && (
                <p className="px-4 py-6 text-center text-xs text-gray-400">Loading...</p>
              )}
              {!loadingHistory && conversations.length === 0 && (
                <p className="px-4 py-6 text-center text-xs text-gray-400">No runs yet</p>
              )}
              {conversations.map((conv) => (
                <div
                  key={conv.id}
                  onClick={() => { if (editingId !== conv.id) loadConversation(conv); }}
                  className={`group flex w-full cursor-pointer items-start justify-between gap-2 border-b border-gray-200 px-4 py-3 text-left transition hover:bg-gray-100 ${
                    conv.id === conversationId ? "bg-indigo-50" : ""
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    {editingId === conv.id ? (
                      <form onSubmit={(e) => saveTitle(e, conv.id)} className="flex items-center gap-1">
                        <input
                          autoFocus
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onBlur={(e) => saveTitle(e, conv.id)}
                          onKeyDown={(e) => { if (e.key === "Escape") setEditingId(null); }}
                          onClick={(e) => e.stopPropagation()}
                          className="w-full rounded border border-indigo-300 px-1.5 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
                        />
                      </form>
                    ) : (
                      <span className="block truncate text-sm font-medium text-gray-800">
                        {conv.title || `Run ${conv.id.slice(0, 8)}`}
                      </span>
                    )}
                    <span className="text-xs text-gray-400">
                      {new Date(conv.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </span>
                    {conv.summary && (
                      <span className="mt-0.5 line-clamp-2 block text-xs text-gray-500">{conv.summary}</span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    {confirmDeleteId === conv.id ? (
                      <>
                        <span className="mr-1 text-xs text-red-500">Delete?</span>
                        <button
                          onClick={(e) => deleteConversation(e, conv)}
                          className="rounded p-1 text-red-500 hover:bg-red-50"
                          title="Confirm delete"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                          </svg>
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(null); }}
                          className="rounded p-1 text-gray-400 hover:bg-gray-200"
                          title="Cancel"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={(e) => startEditing(e, conv)}
                          className="rounded p-1 text-gray-400 opacity-0 transition hover:bg-gray-200 hover:text-gray-600 group-hover:opacity-100"
                          title="Rename run"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
                          </svg>
                        </button>
                        <button
                          onClick={(e) => deleteConversation(e, conv)}
                          className="rounded p-1 text-gray-400 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                          title="Delete run"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                          </svg>
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      {/* Messages area */}
      <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <svg className="mx-auto mb-4 h-12 w-12 text-indigo-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
              </svg>
              <p className="text-lg font-medium text-gray-700">How can I help you today?</p>
              <p className="mt-1 text-sm text-gray-500">
                Ask me about datasets, tools, pipelines, apps or agents on the platform.
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {[
                  "Show me an overview of the platform",
                  "What datasets are available?",
                  "List all available agents",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => { setInput(suggestion); inputRef.current?.focus(); }}
                    className="rounded-full border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`mb-4 flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-2.5 ${
                msg.role === "user" ? "bg-indigo-100 text-indigo-900" : "bg-gray-100 text-gray-900"
              }`}
            >
              {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="mb-2 space-y-1">
                  {msg.tool_calls.map((tc, j) => (
                    <div key={j} className="flex items-center gap-1.5 rounded bg-gray-200/60 px-2 py-1 text-xs text-gray-600">
                      <svg className="h-3 w-3 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.048.58.024 1.194-.14 1.743" />
                      </svg>
                      <span className="font-medium">{tc.name}</span>
                      {tc.args && Object.keys(tc.args).length > 0 && (
                        <span className="text-gray-400">({Object.entries(tc.args).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ")})</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {msg.tool_results && msg.tool_results.length > 0 && (
                <div className="mb-2 space-y-1">
                  {msg.tool_results.map((tr, j) => (
                    <details key={j} className="rounded bg-green-50 px-2 py-1 text-xs text-green-800">
                      <summary className="cursor-pointer font-medium">
                        <span className="ml-1">{tr.name}</span> — result received
                      </summary>
                      <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-[10px] text-green-700">{tr.result.length > 500 ? tr.result.slice(0, 500) + "..." : tr.result}</pre>
                    </details>
                  ))}
                </div>
              )}
              {msg.delegation && (
                <div className={`mb-2 rounded px-2 py-1.5 text-xs ${msg.delegation.status === "running" ? "bg-blue-50 text-blue-700" : msg.delegation.status === "completed" ? "bg-purple-50 text-purple-800" : "bg-red-50 text-red-700"}`}>
                  <div className="flex items-center gap-1.5">
                    {msg.delegation.status === "running" && (
                      <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                    )}
                    {msg.delegation.status === "completed" && (
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                      </svg>
                    )}
                    <span className="font-medium">
                      Delegating to agent: {msg.delegation.agent_id}
                    </span>
                  </div>
                  <p className="mt-0.5 text-gray-500">Task: {msg.delegation.task}</p>
                  {msg.delegation.result && (
                    <details className="mt-1">
                      <summary className="cursor-pointer font-medium">Sub-agent response</summary>
                      <div className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white/60 p-2 text-[11px] text-gray-800">
                        {msg.delegation.result}
                      </div>
                    </details>
                  )}
                </div>
              )}
              <div className="prose prose-sm max-w-none text-sm leading-relaxed dark:prose-invert prose-p:my-1 prose-pre:my-2 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-headings:my-2">
                {msg.role === "assistant" && msg.content ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                ) : (
                  <span className="whitespace-pre-wrap">{msg.content}</span>
                )}
                {streaming && i === messages.length - 1 && msg.role === "assistant" && !msg.content && !msg.tool_calls?.length && !msg.delegation && (
                  <div className="flex items-center gap-2 text-indigo-600">
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span className="text-sm font-medium animate-pulse">Thinking...</span>
                  </div>
                )}
                {streaming && i === messages.length - 1 && msg.role === "assistant" && !msg.content && (msg.tool_calls?.length || msg.delegation) && (
                  <div className="flex items-center gap-2 text-indigo-600 mt-2">
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span className="text-sm font-medium animate-pulse">Working...</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-gray-200 bg-white px-6 py-4">
        {streaming && (
          <div className="mb-3 flex items-center justify-center">
            <div className="flex items-center gap-2 rounded-full bg-indigo-50 border border-indigo-200 px-4 py-1.5">
              <svg className="h-3.5 w-3.5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              <span className="text-xs font-medium text-indigo-700">Assistant is working</span>
            </div>
          </div>
        )}
        <div className="flex items-end gap-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the Platform Assistant..."
            rows={1}
            className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            style={{ maxHeight: "120px" }}
            disabled={streaming}
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || streaming}
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-700 disabled:opacity-50"
          >
            {streaming ? (
              <svg className="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            ) : (
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" />
              </svg>
            )}
          </button>
        </div>
        {conversationId && (
          <p className="mt-1.5 text-xs text-gray-400">
            Run: {conversationId.slice(0, 8)}...
            {(() => { const t = conversations.find((c) => c.id === conversationId)?.title; return t ? ` — ${t.length > 30 ? t.slice(0, 30) + "..." : t}` : ""; })()}
          </p>
        )}
      </div>
      </div>{/* end messages column */}
      </div>{/* end flex row */}
    </div>
  );
}
