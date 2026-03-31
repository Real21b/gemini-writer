import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Send, Sparkles, BookOpen, BookText, Library } from "lucide-react";

const TEMPLATES = [
  {
    icon: BookOpen,
    title: "Novel",
    prompt: "Write a mystery novel set in Victorian London with 10 chapters",
  },
  {
    icon: Library,
    title: "Short Story Collection",
    prompt:
      "Create a collection of 7 interconnected sci-fi short stories exploring the theme of memory",
  },
  {
    icon: BookText,
    title: "Non-Fiction Book",
    prompt:
      "Write a comprehensive guide to Python programming with 15 chapters",
  },
];

export default function NewProject() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) return;

    setSubmitting(true);
    setError("");

    try {
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), prompt: prompt.trim() }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to create project");
      }
      const project = await res.json();
      navigate(`/project/${project.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function applyTemplate(tpl) {
    setName(tpl.title);
    setPrompt(tpl.prompt);
  }

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white">New Writing Project</h1>
        <p className="text-gray-400 mt-1">
          Describe what you want to create and let the AI agent handle the rest.
        </p>
      </div>

      {/* Templates */}
      <div>
        <h2 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-primary-400" />
          Quick Templates
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {TEMPLATES.map((tpl) => (
            <button
              key={tpl.title}
              type="button"
              onClick={() => applyTemplate(tpl)}
              className="text-left p-4 bg-gray-900 border border-gray-800 rounded-xl hover:border-primary-600/50 hover:bg-gray-900/80 transition-all group"
            >
              <tpl.icon className="w-5 h-5 text-primary-400 mb-2 group-hover:scale-110 transition-transform" />
              <div className="text-white text-sm font-medium">{tpl.title}</div>
              <div className="text-gray-500 text-xs mt-1 line-clamp-2">
                {tpl.prompt}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-5">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Project Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Sci-Fi Novel"
            className="w-full px-4 py-3 bg-gray-900 border border-gray-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Writing Prompt
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe what you want the AI to create..."
            rows={6}
            className="w-full px-4 py-3 bg-gray-900 border border-gray-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all resize-none"
            required
          />
          <p className="text-gray-500 text-xs mt-2">
            Be specific for best results. Include genre, length, themes, and any
            other details.
          </p>
        </div>

        <button
          type="submit"
          disabled={submitting || !name.trim() || !prompt.trim()}
          className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-primary-600 hover:bg-primary-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium transition-colors shadow-lg shadow-primary-600/20"
        >
          <Send className="w-4 h-4" />
          {submitting ? "Creating…" : "Create & Start Writing"}
        </button>
      </form>
    </div>
  );
}
