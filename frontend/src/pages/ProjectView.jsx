import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import {
  ArrowLeft,
  Brain,
  FileText,
  Loader2,
  Play,
  CheckCircle2,
  AlertCircle,
  Wrench,
  Zap,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import useWebSocket from "../hooks/useWebSocket";

export default function ProjectView() {
  const { id } = useParams();
  const [project, setProject] = useState(null);
  const [files, setFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState("");
  const [started, setStarted] = useState(false);
  const [showThinking, setShowThinking] = useState(false);

  const feedRef = useRef(null);

  // WebSocket URL (only valid after clicking Start)
  const wsUrl = useMemo(() => {
    if (!started || !id) return null;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/ws/write/${id}`;
  }, [started, id]);

  const { messages, status, connect } = useWebSocket(wsUrl);

  // Connect once URL is ready
  useEffect(() => {
    if (wsUrl) connect();
  }, [wsUrl, connect]);

  // Fetch project info
  useEffect(() => {
    fetchProject();
    const interval = setInterval(fetchProject, 3000);
    return () => clearInterval(interval);
  }, [id]);

  // Auto-scroll feed
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [messages]);

  // Auto-start if project is pending
  useEffect(() => {
    if (project && project.status === "pending" && !started) {
      setStarted(true);
    }
  }, [project, started]);

  // Fetch files when project updates or when we receive tool results
  useEffect(() => {
    if (project) fetchFiles();
  }, [project, messages.length]);

  async function fetchProject() {
    try {
      const res = await fetch(`/api/projects/${id}`);
      if (res.ok) setProject(await res.json());
    } catch {
      // ignore
    }
  }

  async function fetchFiles() {
    try {
      const res = await fetch(`/api/projects/${id}/files`);
      if (res.ok) {
        const data = await res.json();
        setFiles(data.files);
      }
    } catch {
      // ignore
    }
  }

  async function openFile(filename) {
    setSelectedFile(filename);
    try {
      const res = await fetch(`/api/projects/${id}/files/${filename}`);
      if (res.ok) {
        const data = await res.json();
        setFileContent(data.content);
      }
    } catch {
      setFileContent("Error loading file.");
    }
  }

  // Derived state
  const latestProgress = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].type === "progress") return messages[i].data;
    }
    return null;
  }, [messages]);

  const isDone = messages.some((m) => m.type === "done");
  const hasError = messages.some((m) => m.type === "error");

  return (
    <div className="space-y-6">
      {/* Breadcrumb + Title */}
      <div className="flex items-center gap-3">
        <Link
          to="/"
          className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-white">
            {project?.name || "Loading…"}
          </h1>
          <p className="text-gray-500 text-sm mt-0.5 truncate max-w-xl">
            {project?.prompt}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      {latestProgress && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center justify-between text-sm text-gray-400 mb-2">
            <span className="flex items-center gap-2">
              {isDone ? (
                <CheckCircle2 className="w-4 h-4 text-green-400" />
              ) : hasError ? (
                <AlertCircle className="w-4 h-4 text-red-400" />
              ) : (
                <Loader2 className="w-4 h-4 text-primary-400 animate-spin" />
              )}
              Iteration {latestProgress.iteration}/{latestProgress.max_iterations}
            </span>
            <span className="flex items-center gap-1">
              <Zap className="w-3 h-3" />
              {latestProgress.tokens?.toLocaleString()}/{latestProgress.token_limit?.toLocaleString()} tokens
            </span>
          </div>
          <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                isDone ? "bg-green-500" : hasError ? "bg-red-500" : "bg-primary-500"
              }`}
              style={{
                width: `${Math.min(
                  (latestProgress.iteration / latestProgress.max_iterations) * 100,
                  100
                )}%`,
              }}
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Event feed */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-2xl flex flex-col overflow-hidden max-h-[70vh]">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
            <h2 className="text-sm font-medium text-gray-300">Agent Feed</h2>
            <button
              onClick={() => setShowThinking(!showThinking)}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors flex items-center gap-1"
            >
              <Brain className="w-3 h-3" />
              {showThinking ? "Hide" : "Show"} Thinking
            </button>
          </div>

          <div ref={feedRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && status === "connected" && (
              <div className="text-center text-gray-500 py-12">
                <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-primary-500" />
                Waiting for AI agent to start…
              </div>
            )}

            {messages.map((msg, i) => (
              <FeedItem
                key={i}
                msg={msg}
                showThinking={showThinking}
              />
            ))}

            {isDone && (
              <div className="text-center py-6">
                <CheckCircle2 className="w-10 h-10 text-green-400 mx-auto mb-2" />
                <p className="text-green-400 font-medium">Writing Complete!</p>
                <p className="text-gray-500 text-sm mt-1">
                  Check the files panel to read your content.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Right: Files sidebar */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl flex flex-col overflow-hidden max-h-[70vh]">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="text-sm font-medium text-gray-300 flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary-400" />
              Files ({files.length})
            </h2>
          </div>

          {files.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-sm p-4">
              No files generated yet
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {/* File list */}
              <div className="divide-y divide-gray-800">
                {files.map((f) => (
                  <button
                    key={f.name}
                    onClick={() => openFile(f.name)}
                    className={`w-full text-left px-4 py-3 hover:bg-gray-800/50 transition-colors ${
                      selectedFile === f.name ? "bg-gray-800/50" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-gray-500" />
                      <span className="text-sm text-gray-300 truncate">
                        {f.name}
                      </span>
                    </div>
                    <span className="text-xs text-gray-600 ml-6">
                      {(f.size / 1024).toFixed(1)} KB
                    </span>
                  </button>
                ))}
              </div>

              {/* File preview */}
              {selectedFile && (
                <div className="border-t border-gray-800 p-4">
                  <h3 className="text-xs font-medium text-gray-400 mb-3">
                    {selectedFile}
                  </h3>
                  <div className="prose-writer text-sm max-h-80 overflow-y-auto">
                    <ReactMarkdown>{fileContent}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Feed Item Component ───────────────────────────────────────────── */

function FeedItem({ msg, showThinking }) {
  const [expanded, setExpanded] = useState(false);
  const { type, data } = msg;

  if (type === "thinking" && !showThinking) return null;

  if (type === "status") {
    return (
      <div className="animate-fade-in flex items-center gap-2 text-sm text-gray-500">
        <div className="w-1.5 h-1.5 rounded-full bg-gray-600" />
        {data.message}
      </div>
    );
  }

  if (type === "progress") return null; // Shown in the progress bar instead

  if (type === "config") return null;

  if (type === "thinking") {
    return (
      <div className="animate-fade-in bg-purple-500/5 border border-purple-500/10 rounded-xl p-3">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 text-xs text-purple-400 w-full"
        >
          <Brain className="w-3 h-3" />
          <span>Thinking (Iteration {data.iteration})</span>
          {expanded ? (
            <ChevronDown className="w-3 h-3 ml-auto" />
          ) : (
            <ChevronRight className="w-3 h-3 ml-auto" />
          )}
        </button>
        {expanded && (
          <p className="mt-2 text-xs text-purple-300/70 whitespace-pre-wrap max-h-40 overflow-y-auto">
            {data.text}
          </p>
        )}
      </div>
    );
  }

  if (type === "content") {
    return (
      <div className="animate-fade-in bg-gray-800/50 border border-gray-700/50 rounded-xl p-4">
        <div className="text-xs text-gray-500 mb-2">
          Response · Iteration {data.iteration}
        </div>
        <div className="prose-writer text-sm">
          <ReactMarkdown>{data.text}</ReactMarkdown>
        </div>
      </div>
    );
  }

  if (type === "tool_call") {
    return (
      <div className="animate-fade-in flex items-start gap-2 text-sm">
        <Wrench className="w-4 h-4 text-yellow-400 mt-0.5 shrink-0" />
        <div>
          <span className="text-yellow-400 font-medium">{data.name}</span>
          <span className="text-gray-500 ml-2 text-xs">
            {JSON.stringify(data.args).substring(0, 120)}
          </span>
        </div>
      </div>
    );
  }

  if (type === "tool_result") {
    return (
      <div className="animate-fade-in flex items-start gap-2 text-sm ml-6">
        <CheckCircle2 className="w-3.5 h-3.5 text-green-400 mt-0.5 shrink-0" />
        <span className="text-gray-400 text-xs truncate max-w-md">
          {data.result}
        </span>
      </div>
    );
  }

  if (type === "error") {
    return (
      <div className="animate-fade-in bg-red-500/10 border border-red-500/20 rounded-xl p-3">
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          {data.message}
        </div>
      </div>
    );
  }

  if (type === "done") {
    return null; // Handled separately
  }

  return null;
}
