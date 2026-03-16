import { useEffect, useState } from 'react';
import { fetchAgents } from '../api/agents';
import type { Agent } from '../types/agent';

interface Schedule {
  id: number;
  agent_id: string;
  interval_hours: number;
  prompt: string;
  last_dispatched_at: number | null;
  created_at: string;
}

function formatRelativeTime(timestamp: number | string | null): string {
  if (!timestamp) return 'Never';
  const ts = typeof timestamp === 'string' ? new Date(timestamp + 'Z').getTime() / 1000 : timestamp;
  if (ts === 0) return 'Never';
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatCreatedAt(dateStr: string): string {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'Z');
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatInterval(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours === Math.floor(hours)) return `${hours}h`;
  return `${hours}h`;
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

async function fetchSchedules(): Promise<Schedule[]> {
  const res = await fetch('/api/v1/schedules');
  if (!res.ok) throw new Error(`Failed to fetch schedules: ${res.status}`);
  return res.json();
}

async function createSchedule(data: { agent_id: string; interval_hours: number; prompt: string }): Promise<Schedule> {
  const res = await fetch('/api/v1/schedules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Unknown error' }));
    throw new Error(err.error || `Failed to create schedule: ${res.status}`);
  }
  return res.json();
}

async function deleteSchedule(id: number): Promise<void> {
  const res = await fetch(`/api/v1/schedules/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed to delete schedule: ${res.status}`);
}

export default function Schedules() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Form state
  const [formAgentId, setFormAgentId] = useState('');
  const [formInterval, setFormInterval] = useState('24');
  const [formPrompt, setFormPrompt] = useState('');
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Load schedules and agents
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [scheds, agts] = await Promise.all([fetchSchedules(), fetchAgents()]);
        if (active) {
          setSchedules(scheds);
          setAgents(agts);
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!formAgentId || !formInterval || !formPrompt.trim()) {
      setFormError('All fields are required');
      return;
    }
    const intervalNum = parseFloat(formInterval);
    if (isNaN(intervalNum) || intervalNum <= 0) {
      setFormError('Interval must be a positive number');
      return;
    }
    setCreating(true);
    setFormError(null);
    try {
      await createSchedule({
        agent_id: formAgentId,
        interval_hours: intervalNum,
        prompt: formPrompt.trim(),
      });
      // Refresh list
      const scheds = await fetchSchedules();
      setSchedules(scheds);
      // Reset form
      setFormAgentId('');
      setFormInterval('24');
      setFormPrompt('');
      setShowForm(false);
    } catch (e) {
      setFormError(String(e));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: number) {
    setDeleting(true);
    try {
      await deleteSchedule(id);
      const scheds = await fetchSchedules();
      setSchedules(scheds);
      setDeleteConfirm(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setDeleting(false);
    }
  }

  if (loading) {
    return (
      <div>
        <Skeleton className="h-8 w-48 mb-6" />
        <Skeleton className="h-12 w-full mb-4" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error && schedules.length === 0) {
    return (
      <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">
        Error: {error}
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Scheduled Jobs</h2>
        <button
          onClick={() => {
            setShowForm(!showForm);
            setFormError(null);
          }}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            showForm
              ? 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {showForm ? 'Cancel' : 'Create Schedule'}
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-3 rounded text-sm">
          {error}
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <div className="mb-6 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-5">
          <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-4">New Schedule</h3>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Agent select */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Agent
                </label>
                <select
                  value={formAgentId}
                  onChange={(e) => setFormAgentId(e.target.value)}
                  className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Select agent...</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.id}
                    </option>
                  ))}
                </select>
              </div>
              {/* Interval */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Interval (hours)
                </label>
                <input
                  type="number"
                  step="0.5"
                  min="0.1"
                  value={formInterval}
                  onChange={(e) => setFormInterval(e.target.value)}
                  placeholder="e.g. 24, 4, 0.5"
                  className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            {/* Prompt */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Prompt
              </label>
              <textarea
                value={formPrompt}
                onChange={(e) => setFormPrompt(e.target.value)}
                rows={3}
                placeholder="Task description for the agent..."
                className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
              />
            </div>
            {/* Form error */}
            {formError && (
              <div className="text-red-600 dark:text-red-400 text-sm">{formError}</div>
            )}
            {/* Submit */}
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={creating}
                className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Table */}
      {schedules.length === 0 ? (
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-12 text-center">
          <div className="text-4xl mb-3">&#128336;</div>
          <h3 className="text-lg font-medium text-gray-800 dark:text-gray-200 mb-1">No scheduled jobs</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Create a schedule to automatically dispatch agents at regular intervals.
          </p>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Agent</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Interval</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Prompt</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Last Run</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Created</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {schedules.map((s) => (
                  <tr key={s.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300">
                        {s.agent_id}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-700 dark:text-gray-300 font-mono">
                      {formatInterval(s.interval_hours)}
                    </td>
                    <td className="px-4 py-3 max-w-xs">
                      <span
                        className="text-gray-700 dark:text-gray-300 truncate block"
                        title={s.prompt}
                      >
                        {s.prompt}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                      {formatRelativeTime(s.last_dispatched_at)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                      {formatCreatedAt(s.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {deleteConfirm === s.id ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-xs text-gray-500 dark:text-gray-400">Delete?</span>
                          <button
                            onClick={() => handleDelete(s.id)}
                            disabled={deleting}
                            className="px-2 py-1 text-xs font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded hover:bg-red-100 dark:hover:bg-red-900/40 disabled:opacity-50 transition-colors"
                          >
                            {deleting ? '...' : 'Yes'}
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(null)}
                            className="px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                          >
                            No
                          </button>
                        </span>
                      ) : (
                        <button
                          onClick={() => setDeleteConfirm(s.id)}
                          className="px-2 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                          title="Delete schedule"
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
