import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchAgents } from '../api/agents';
import type { Agent } from '../types/agent';
import StatusBadge from '../components/StatusBadge';

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

export default function Dashboard() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const data = await fetchAgents();
        if (active) {
          setAgents(data);
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }

    poll();
    const interval = setInterval(poll, 5000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  async function handleDispatchAll() {
    setDispatching(true);
    setDispatchResult(null);
    try {
      const res = await fetch('/api/v1/agents/dispatch-all', { method: 'POST' });
      const data = await res.json();
      const summary = Object.entries(data).map(([a, s]) => `${a}: ${s}`).join(', ');
      setDispatchResult(summary);
      setTimeout(() => setDispatchResult(null), 5000);
    } catch (e) {
      setDispatchResult(`Error: ${e}`);
    } finally {
      setDispatching(false);
    }
  }

  if (loading) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-10 w-32" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
              <Skeleton className="h-5 w-24 mb-3" />
              <Skeleton className="h-4 w-32 mb-3" />
              <Skeleton className="h-3 w-full" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Dashboard</h2>
        <button
          onClick={handleDispatchAll}
          disabled={dispatching}
          className="px-4 py-2 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-700 disabled:opacity-50"
        >
          {dispatching ? 'Dispatching...' : 'Dispatch All'}
        </button>
      </div>
      {dispatchResult && (
        <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded text-sm text-green-800 dark:text-green-300">
          {dispatchResult}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: Agent }) {
  const wl = agent.workload;
  return (
    <Link to={`/agents/${agent.id}`} className="block bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4 shadow-sm hover:shadow-md dark:hover:border-gray-600 transition-all">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">{agent.id}</h3>
        <StatusBadge status={agent.tmux_status} />
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">{agent.role}</p>
      {agent.profile?.current_context && (
        <p className="text-xs text-gray-600 dark:text-gray-400 mb-3 italic truncate">
          {agent.profile.current_context}
        </p>
      )}
      <div className="flex gap-3 text-xs text-gray-500 dark:text-gray-400">
        <span title="In Progress">
          <span className="font-medium text-yellow-600 dark:text-yellow-400">{wl.in_progress}</span> active
        </span>
        <span title="New">
          <span className="font-medium text-blue-600 dark:text-blue-400">{wl.new}</span> new
        </span>
        <span title="Blocked">
          <span className="font-medium text-gray-600 dark:text-gray-400">{wl.blocked}</span> blocked
        </span>
      </div>
    </Link>
  );
}
