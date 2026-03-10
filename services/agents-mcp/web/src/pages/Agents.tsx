import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchAgents } from '../api/agents';
import type { Agent } from '../types/agent';
import StatusBadge from '../components/StatusBadge';

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

export default function Agents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  if (loading) {
    return (
      <div>
        <Skeleton className="h-8 w-32 mb-6" />
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4 space-y-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      </div>
    );
  }

  if (error) return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-6">Agents</h2>
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Agent</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Role</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Active</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">New</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Blocked</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300 hidden sm:table-cell">Context</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {agents.map((agent) => (
              <tr key={agent.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <td className="px-4 py-3 font-medium">
                  <Link to={`/agents/${agent.id}`} className="text-blue-600 dark:text-blue-400 hover:underline">
                    {agent.id}
                  </Link>
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{agent.role}</td>
                <td className="px-4 py-3"><StatusBadge status={agent.tmux_status} /></td>
                <td className="px-4 py-3 text-center text-gray-700 dark:text-gray-300">{agent.workload.in_progress}</td>
                <td className="px-4 py-3 text-center text-gray-700 dark:text-gray-300">{agent.workload.new}</td>
                <td className="px-4 py-3 text-center text-gray-700 dark:text-gray-300">{agent.workload.blocked}</td>
                <td className="px-4 py-3 text-gray-500 dark:text-gray-400 truncate max-w-xs hidden sm:table-cell">
                  {agent.profile?.current_context || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
