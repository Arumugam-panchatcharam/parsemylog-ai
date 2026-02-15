import { useState, useEffect, useRef, useCallback } from "react";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import { chatApi } from "@/api/endpoints";
import { patternsApi } from "@/api/endpoints";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import PersonIcon from "@mui/icons-material/Person";
import SendIcon from "@mui/icons-material/Send";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import ChatIcon from "@mui/icons-material/Chat";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import CircularProgress from "@mui/material/CircularProgress";
import { cn } from "@/lib/utils";

/* ================================================================ Types */
interface Conversation {
  id: number;
  title: string;
  cpe_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface Message {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  context_used: Record<string, unknown> | null;
  created_at: string | null;
}

/* ================================================================ Main */
export default function ChatPage() {
  const { projectId, projectName } = useProject();
  const { cpeId } = useCPE();

  // Gate states
  const [gateLoading, setGateLoading] = useState(true);
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [indexingDone, setIndexingDone] = useState(false);

  // Conversation states
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingConvs, setLoadingConvs] = useState(false);
  const [loadingMsgs, setLoadingMsgs] = useState(false);

  // Chat input
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [streamContext, setStreamContext] = useState<Record<string, unknown> | null>(null);
  const [statusMessage, setStatusMessage] = useState("");

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ------------------------------------------------------------------ Gate check
  useEffect(() => {
    if (!projectId) return;
    setGateLoading(true);

    Promise.all([
      chatApi.llmStatus(projectId),
      patternsApi.indexingStatus(projectId, cpeId),
    ])
      .then(([llmRes, idxRes]) => {
        setLlmEnabled(llmRes.data.enabled);
        setLlmAvailable(llmRes.data.available);
        setIndexingDone(idxRes.data.all_done ?? false);
      })
      .catch(() => {
        setLlmEnabled(false);
        setLlmAvailable(false);
      })
      .finally(() => setGateLoading(false));
  }, [projectId, cpeId]);

  // ------------------------------------------------------------------ Load conversations
  const loadConversations = useCallback(async () => {
    if (!projectId) return;
    setLoadingConvs(true);
    try {
      const res = await chatApi.listConversations(projectId, cpeId);
      setConversations(res.data);
    } catch {
      setConversations([]);
    } finally {
      setLoadingConvs(false);
    }
  }, [projectId, cpeId]);

  useEffect(() => {
    if (llmEnabled && llmAvailable) {
      loadConversations();
    }
  }, [llmEnabled, llmAvailable, loadConversations]);

  // ------------------------------------------------------------------ Load messages
  useEffect(() => {
    if (!activeConvId || !projectId) {
      setMessages([]);
      return;
    }
    setLoadingMsgs(true);
    chatApi
      .getMessages(projectId, activeConvId)
      .then((res) => setMessages(res.data))
      .catch(() => setMessages([]))
      .finally(() => setLoadingMsgs(false));
  }, [activeConvId, projectId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamContent]);

  // ------------------------------------------------------------------ Create conversation
  const handleNewConversation = async () => {
    if (!projectId) return;
    try {
      const res = await chatApi.createConversation(projectId, "New conversation", cpeId);
      setConversations((prev) => [{ ...res.data, created_at: null, updated_at: null }, ...prev]);
      setActiveConvId(res.data.id);
      setMessages([]);
    } catch (err) {
      console.error("Failed to create conversation:", err);
    }
  };

  // ------------------------------------------------------------------ Delete conversation
  const handleDeleteConversation = async (convId: number) => {
    if (!projectId) return;
    try {
      await chatApi.deleteConversation(projectId, convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      if (activeConvId === convId) {
        setActiveConvId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  // ------------------------------------------------------------------ Send message
  const handleSend = async () => {
    if (!projectId || !activeConvId || !input.trim() || streaming) return;

    const userMsg = input.trim();
    setInput("");
    setStreaming(true);
    setStreamContent("");
    setStreamContext(null);
    setStatusMessage("");

    // Optimistic: add user message to UI
    const tmpUserMsg: Message = {
      id: Date.now(),
      role: "user",
      content: userMsg,
      context_used: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tmpUserMsg]);

    try {
      const token = localStorage.getItem("access_token");
      const apiBase = import.meta.env.VITE_API_URL || "";

      const response = await fetch(
        `${apiBase}/api/projects/${projectId}/chat/send`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            conversation_id: activeConvId,
            message: userMsg,
          }),
        }
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response stream");

      const decoder = new TextDecoder();
      let accumulated = "";
      let fullContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        accumulated += decoder.decode(value, { stream: true });
        const lines = accumulated.split("\n");
        accumulated = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            const eventType = line.slice(7).trim();
            // next line should be "data: ..."
            continue;
          }
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              // Parse by checking which fields exist
              if (data.token !== undefined) {
                fullContent += data.token;
                setStreamContent(fullContent);
              } else if (data.evidence_sources !== undefined) {
                setStreamContext(data);
              } else if (data.message === "complete") {
                // done
              } else if (data.error) {
                fullContent += `\n\n**Error**: ${data.error}`;
                setStreamContent(fullContent);
              } else if (data.message && data.message !== "complete") {
                setStatusMessage(data.message);
              }
            } catch {
              // not JSON, skip
            }
          }
        }
      }

      // Add the assistant message
      if (fullContent) {
        const assistantMsg: Message = {
          id: Date.now() + 1,
          role: "assistant",
          content: fullContent,
          context_used: streamContext,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (err) {
      const errMsg: Message = {
        id: Date.now() + 2,
        role: "assistant",
        content: `**Error**: ${err instanceof Error ? err.message : "Failed to get response"}`,
        context_used: null,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setStreaming(false);
      setStreamContent("");
      setStatusMessage("");
      // Refresh conversations list for updated title
      loadConversations();
    }
  };

  // ------------------------------------------------------------------ Keyboard shortcut
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ------------------------------------------------------------------ Gate UI
  if (gateLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <CircularProgress size={32} />
      </div>
    );
  }

  if (!llmEnabled) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
        <SmartToyIcon style={{ fontSize: 64, opacity: 0.3 }} />
        <h2 className="text-xl font-semibold text-muted-foreground">AI Chat is disabled</h2>
        <p className="text-sm text-muted-foreground max-w-md">
          The AI Chat feature has been disabled by your admin. Contact them to enable it in the Admin Panel.
        </p>
      </div>
    );
  }

  if (!llmAvailable) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
        <SmartToyIcon style={{ fontSize: 64, opacity: 0.3 }} />
        <h2 className="text-xl font-semibold text-muted-foreground">LLM Server Unavailable</h2>
        <p className="text-sm text-muted-foreground max-w-md">
          The LLM server is not responding. Please check that the LLM service is running and try again.
        </p>
      </div>
    );
  }

  if (!indexingDone) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
        <CircularProgress size={48} />
        <h2 className="text-xl font-semibold text-muted-foreground">Indexing in Progress</h2>
        <p className="text-sm text-muted-foreground max-w-md">
          AI Chat will be available after log parsing and indexing is complete. Please check back shortly.
        </p>
      </div>
    );
  }

  // ================================================================== Main UI
  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
      {/* ---- Left Panel: Conversation List ---- */}
      <div className="w-64 shrink-0 border-r border-border flex flex-col bg-muted/30">
        <div className="p-3 border-b border-border">
          <button
            onClick={handleNewConversation}
            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <AddIcon style={{ fontSize: 18 }} />
            New Chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loadingConvs ? (
            <div className="flex justify-center py-4">
              <CircularProgress size={20} />
            </div>
          ) : conversations.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-4">
              No conversations yet
            </p>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={cn(
                  "group flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors",
                  activeConvId === conv.id
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-foreground hover:bg-muted"
                )}
                onClick={() => setActiveConvId(conv.id)}
              >
                <ChatIcon style={{ fontSize: 16 }} className="shrink-0 opacity-60" />
                <span className="truncate flex-1">{conv.title}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteConversation(conv.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all"
                >
                  <DeleteIcon style={{ fontSize: 14 }} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ---- Right Panel: Chat Area ---- */}
      <div className="flex-1 flex flex-col min-w-0">
        {!activeConvId ? (
          /* Empty state */
          <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
            <SmartToyIcon style={{ fontSize: 64, opacity: 0.15 }} />
            <h2 className="text-xl font-semibold text-muted-foreground">AI Log Analyst</h2>
            <p className="text-sm text-muted-foreground max-w-md">
              Ask questions about your CPE logs. The AI uses parsed reboots, error patterns,
              telemetry, and semantic search to ground its responses in actual log evidence.
            </p>
            <button
              onClick={handleNewConversation}
              className="flex items-center gap-2 py-2 px-4 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90"
            >
              <AddIcon style={{ fontSize: 18 }} />
              Start a conversation
            </button>
          </div>
        ) : (
          <>
            {/* Messages area */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
              {loadingMsgs ? (
                <div className="flex justify-center py-8">
                  <CircularProgress size={24} />
                </div>
              ) : messages.length === 0 && !streaming ? (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
                  <SmartToyIcon style={{ fontSize: 48, opacity: 0.15 }} />
                  <p className="text-sm text-muted-foreground">
                    Ask a question about the logs for <strong>{projectName}</strong>
                    {cpeId ? ` (CPE: ${cpeId})` : ""}
                  </p>
                </div>
              ) : (
                <>
                  {messages.map((msg) => (
                    <MessageBubble key={msg.id} message={msg} />
                  ))}

                  {/* Streaming response */}
                  {streaming && streamContent && (
                    <div className="flex gap-3 items-start">
                      <div className="shrink-0 h-8 w-8 rounded-full bg-primary/15 flex items-center justify-center">
                        <SmartToyIcon style={{ fontSize: 18 }} className="text-primary" />
                      </div>
                      <div className="flex-1 min-w-0 bg-muted/50 rounded-xl px-4 py-3 prose prose-sm dark:prose-invert max-w-none">
                        <Markdown remarkPlugins={[remarkGfm]}>{streamContent}</Markdown>
                        <span className="inline-block w-1.5 h-4 bg-primary/60 animate-pulse ml-0.5" />
                      </div>
                    </div>
                  )}

                  {/* Status/queue message */}
                  {streaming && !streamContent && (
                    <div className="flex gap-3 items-center">
                      <div className="shrink-0 h-8 w-8 rounded-full bg-primary/15 flex items-center justify-center">
                        <SmartToyIcon style={{ fontSize: 18 }} className="text-primary" />
                      </div>
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <CircularProgress size={14} />
                        {statusMessage || "Thinking..."}
                      </div>
                    </div>
                  )}
                </>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div className="border-t border-border px-4 py-3">
              <div className="flex gap-2 items-end max-w-3xl mx-auto">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about the logs..."
                  disabled={streaming}
                  rows={1}
                  className="flex-1 resize-none rounded-xl border border-border bg-background px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50 max-h-32"
                  style={{ minHeight: "2.5rem" }}
                  onInput={(e) => {
                    const el = e.target as HTMLTextAreaElement;
                    el.style.height = "auto";
                    el.style.height = Math.min(el.scrollHeight, 128) + "px";
                  }}
                />
                <button
                  onClick={handleSend}
                  disabled={streaming || !input.trim()}
                  className="shrink-0 h-10 w-10 rounded-xl bg-primary text-primary-foreground flex items-center justify-center hover:bg-primary/90 disabled:opacity-40 transition-colors"
                >
                  {streaming ? (
                    <CircularProgress size={18} sx={{ color: "inherit" }} />
                  ) : (
                    <SendIcon style={{ fontSize: 18 }} />
                  )}
                </button>
              </div>
              <p className="text-xs text-muted-foreground text-center mt-1.5">
                Responses are grounded in parsed log evidence. Press Shift+Enter for a new line.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}


/* ================================================================ MessageBubble */
function MessageBubble({ message }: { message: Message }) {
  const [showSources, setShowSources] = useState(false);
  const isUser = message.role === "user";
  const context = message.context_used;

  return (
    <div className={cn("flex gap-3 items-start", isUser && "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "shrink-0 h-8 w-8 rounded-full flex items-center justify-center",
          isUser ? "bg-blue-100 dark:bg-blue-900/30" : "bg-primary/15"
        )}
      >
        {isUser ? (
          <PersonIcon style={{ fontSize: 18 }} className="text-blue-600 dark:text-blue-400" />
        ) : (
          <SmartToyIcon style={{ fontSize: 18 }} className="text-primary" />
        )}
      </div>

      {/* Content */}
      <div
        className={cn(
          "flex-1 min-w-0 rounded-xl px-4 py-3 max-w-[80%]",
          isUser
            ? "bg-blue-50 dark:bg-blue-900/20 ml-auto"
            : "bg-muted/50"
        )}
      >
        {isUser ? (
          <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
          </div>
        )}

        {/* Sources / evidence panel */}
        {!isUser && context && (
          <div className="mt-2 border-t border-border/50 pt-2">
            <button
              onClick={() => setShowSources(!showSources)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <InfoOutlinedIcon style={{ fontSize: 14 }} />
              Sources
              {showSources ? (
                <ExpandLessIcon style={{ fontSize: 14 }} />
              ) : (
                <ExpandMoreIcon style={{ fontSize: 14 }} />
              )}
            </button>

            {showSources && (
              <div className="mt-1.5 text-xs text-muted-foreground space-y-1 bg-background/50 rounded-lg p-2">
                {context.project && (
                  <p>
                    <span className="font-medium">Project:</span> {String(context.project)}
                  </p>
                )}
                {context.cpe_id && (
                  <p>
                    <span className="font-medium">CPE:</span> {String(context.cpe_id)}
                  </p>
                )}
                {Array.isArray(context.evidence_sources) && (
                  <p>
                    <span className="font-medium">Evidence from:</span>{" "}
                    {(context.evidence_sources as string[]).join(", ")}
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
