import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  FolderOpen,
  Clock,
  Zap,
  CheckCircle2,
  AlertCircle,
  Loader2,
  PenLine,
} from "lucide-react";

const STATUS_CONFIG = {
  pending: { color: "text-yellow-400", bg: "bg-yellow-400/10", icon: Clock, label: "Pending" },
  running: { color: "text-blue-400", bg: "bg-blue-400/10", icon: Loader2, label: "Running" },
  completed: { color: "text-green-400", bg: "bg-green-400/10", icon: CheckCircle2, label: "Completed" },
  error: { color: "text-red-400", bg: "bg-red-400/10", icon: AlertCircle, label: "Error" },
  cancelled: { color: "text-gray-400", bg: "bg-gray-400/10", icon: AlertCircle, label: "Cancelled" },
};

export default function Dashboard() {
  const [projects, setProjects] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchProjects();
    const interval = setInterval(fetchProjects, 5000);
    return () => clearInterval(interval);
  }, []);

  async function fetchProjects() {
    try {
      const res = await fetch("/api/projects?limit=50");
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects);
        setTotal(data.total);
      }
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id) {
    if (!confirm("Are you sure you want to delete this project?")) return;
    await fetch(`/api/projects/${id}`, { method: "DELETE" });
    fetchProjects();
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Projects</h1>
          <p className="text-gray-400 mt-1">
            {total} project{total !== 1 && "s"} total
          </p>
        </div>
        <Link
          to="/new"
          className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 hover:bg-primary-500 text-white rounded-xl font-medium transition-colors shadow-lg shadow-primary-600/20"
        >
          <PenLine className="w-4 h-4" />
          New Project
        </Link>
      </div>

      {/* Empty state */}
      {projects.length === 0 && (
        <div className="flex flex-col items-center justify-center h-64 border border-dashed border-gray-700 rounded-2xl bg-gray-900/50">
          <FolderOpen className="w-12 h-12 text-gray-600 mb-4" />
          <p className="text-gray-400 text-lg">No projects yet</p>
          <p className="text-gray-500 text-sm mt-1">
            Create your first project to get started
          </p>
          <Link
            to="/new"
            className="mt-4 px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Create Project
          </Link>
        </div>
      )}

      {/* Project grid */}
      {projects.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => {
            const statusCfg = STATUS_CONFIG[p.status] || STATUS_CONFIG.pending;
            const StatusIcon = statusCfg.icon;
            return (
              <div
                key={p.id}
                className="group relative bg-gray-900 border border-gray-800 rounded-2xl p-5 hover:border-gray-700 transition-all hover:shadow-lg hover:shadow-black/20"
              >
                <Link to={`/project/${p.id}`} className="absolute inset-0 z-10" />

                <div className="flex items-start justify-between mb-3">
                  <h3 className="text-white font-semibold text-lg truncate pr-4">
                    {p.name}
                  </h3>
                  <span
                    className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${statusCfg.bg} ${statusCfg.color}`}
                  >
                    <StatusIcon className={`w-3 h-3 ${p.status === "running" ? "animate-spin" : ""}`} />
                    {statusCfg.label}
                  </span>
                </div>

                <p className="text-gray-400 text-sm line-clamp-2 mb-4">
                  {p.prompt}
                </p>

                {/* Progress bar */}
                {(p.status === "running" || p.status === "completed") && (
                  <div className="mb-3">
                    <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                      <span>Progress</span>
                      <span>{p.progress}%</span>
                    </div>
                    <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          p.status === "completed"
                            ? "bg-green-500"
                            : "bg-primary-500"
                        }`}
                        style={{ width: `${p.progress}%` }}
                      />
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span className="flex items-center gap-1">
                    <Zap className="w-3 h-3" />
                    {p.total_tokens.toLocaleString()} tokens
                  </span>
                  <span>
                    {new Date(p.created_at).toLocaleDateString()}
                  </span>
                </div>

                {/* Delete button */}
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    handleDelete(p.id);
                  }}
                  className="absolute top-3 right-3 z-20 opacity-0 group-hover:opacity-100 p-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all text-xs"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
