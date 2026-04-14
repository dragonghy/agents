import { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import AnsiToHtml from 'ansi-to-html';
import { fetchAgent, fetchAgentTerminal } from '../api/agents';
import { fetchTickets } from '../api/tickets';
import type { Agent } from '../types/agent';
import type { Ticket } from '../types/ticket';
import StatusBadge from '../components/StatusBadge';
import TokenUsagePanel from '../components/TokenUsage';
import JournalPanel from '../components/JournalPanel';

const STATUS_LABELS: Record<number, string> = {
  3: 'New',
  4: 'In Progress',
  1: 'Blocked',
  0: 'Done',
};

const STATUS_COLORS: Record<number, string> = {
  3: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  4: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  1: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  0: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
};

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>();

  const [agent, setAgent] = useState<Agent | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [terminal, setTerminal] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [a, t] = await Promise.all([
          fetchAgent(id!),
          fetchTickets({ assignee: id!, status: '1,3,4' }),
        ]);
        if (active) {
          setAgent(a);
          setTickets(t.tickets);
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 10000);
    return () => { active = false; clearInterval(interval); };
  }, [id]);

  const ansiConverter = useMemo(() => new AnsiToHtml({ fg: '#4ade80', bg: 'transparent', escapeXML: true }), []);

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const data = await fetchAgentTerminal(id!, true);
        if (active) {
          const html = ansiConverter.toHtml(data.output || '');
          setTerminal(html);
        }
      } catch {
        // Terminal may not be available
      }
    }
    poll();
    const interval = setInterval(poll, 3000);
    return () => { active = false; clearInterval(interval); };
  }, [id, ansiConverter]);

  if (loading) {
    return (
      <div>
        <Skeleton className="h-4 w-24 mb-4" />
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="space-y-4">
            <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
              <Skeleton className="h-5 w-20 mb-3" />
              <Skeleton className="h-4 w-full mb-2" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          </div>
          <div className="lg:col-span-2">
            <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
              <Skeleton className="h-48 w-full" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;
  if (!agent) return <div className="text-red-600 dark:text-red-400">Agent not found</div>;

  const profile = agent.profile;

  return (
    <div>
      <div className="mb-4">
        <Link to="/agents" className="text-blue-600 dark:text-blue-400 hover:underline text-sm">&larr; Back to Agents</Link>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100">{agent.id}</h2>
        <StatusBadge status={agent.tmux_status} />
        <span className="text-sm text-gray-500 dark:text-gray-400">{agent.role}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Profile card */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
            <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-3">Profile</h3>
            {profile ? (
              <dl className="space-y-3 text-sm">
                {profile.identity && (
                  <div>
                    <dt className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Identity</dt>
                    <dd className="mt-1 text-gray-800 dark:text-gray-200">{profile.identity}</dd>
                  </div>
                )}
                {profile.current_context && (
                  <div>
                    <dt className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Current Context</dt>
                    <dd className="mt-1 text-gray-800 dark:text-gray-200 italic">{profile.current_context}</dd>
                  </div>
                )}
                {profile.expertise && (
                  <div>
                    <dt className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Expertise</dt>
                    <dd className="mt-1">
                      {(() => {
                        try {
                          const items = JSON.parse(profile.expertise);
                          if (Array.isArray(items)) {
                            return (
                              <div className="flex flex-wrap gap-1">
                                {items.map((item: string) => (
                                  <span key={item} className="px-2 py-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded text-xs">
                                    {item}
                                  </span>
                                ))}
                              </div>
                            );
                          }
                        } catch { /* not JSON */ }
                        return <span className="text-gray-800 dark:text-gray-200">{profile.expertise}</span>;
                      })()}
                    </dd>
                  </div>
                )}
                {profile.updated_at && (
                  <div>
                    <dt className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Last Updated</dt>
                    <dd className="mt-1 text-gray-600 dark:text-gray-400">{profile.updated_at}</dd>
                  </div>
                )}
              </dl>
            ) : (
              <p className="text-sm text-gray-400 dark:text-gray-500">No profile data</p>
            )}
          </div>

          {/* Workload */}
          <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
            <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-3">Workload</h3>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-2 bg-yellow-50 dark:bg-yellow-900/20 rounded">
                <div className="text-xl font-bold text-yellow-600 dark:text-yellow-400">{agent.workload.in_progress}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400">Active</div>
              </div>
              <div className="p-2 bg-blue-50 dark:bg-blue-900/20 rounded">
                <div className="text-xl font-bold text-blue-600 dark:text-blue-400">{agent.workload.new}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400">New</div>
              </div>
              <div className="p-2 bg-gray-50 dark:bg-gray-800 rounded">
                <div className="text-xl font-bold text-gray-600 dark:text-gray-400">{agent.workload.blocked}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400">Blocked</div>
              </div>
            </div>
          </div>

          {/* Token Usage */}
          <TokenUsagePanel agentId={id!} />
        </div>

        {/* Terminal + Tickets */}
        <div className="lg:col-span-2 space-y-6">
          {/* Terminal */}
          <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800">
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
              <h3 className="font-semibold text-gray-800 dark:text-gray-100">Terminal</h3>
              <span className="text-xs text-gray-400">Auto-refresh: 3s</span>
            </div>
            <div className="p-2">
              <pre className="bg-gray-900 dark:bg-black text-green-400 p-3 rounded text-xs font-mono overflow-auto whitespace-pre"
                   style={{ maxHeight: '400px', minHeight: '200px' }}
                   dangerouslySetInnerHTML={{ __html: terminal || 'Terminal not available' }}
              />
            </div>
          </div>

          {/* Assigned Tickets */}
          <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800">
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800">
              <h3 className="font-semibold text-gray-800 dark:text-gray-100">Assigned Tickets ({tickets.length})</h3>
            </div>
            {tickets.length === 0 ? (
              <div className="p-4 text-sm text-gray-400 dark:text-gray-500">No active tickets</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">ID</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">Title</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">Status</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">Priority</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {tickets.map((ticket) => (
                    <tr key={ticket.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                      <td className="px-4 py-2 text-gray-500">
                        <Link to={`/tickets/${ticket.id}`} className="text-blue-600 dark:text-blue-400 hover:underline">
                          #{ticket.id}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-gray-900 dark:text-gray-100">
                        <Link to={`/tickets/${ticket.id}`} className="hover:underline">
                          {ticket.headline}
                        </Link>
                      </td>
                      <td className="px-4 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          STATUS_COLORS[ticket.status] || 'bg-gray-100 dark:bg-gray-800'
                        }`}>
                          {STATUS_LABELS[ticket.status] || ticket.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-gray-600 dark:text-gray-400">{ticket.priority || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Journal */}
          <JournalPanel agentId={id!} />
        </div>
      </div>
    </div>
  );
}
