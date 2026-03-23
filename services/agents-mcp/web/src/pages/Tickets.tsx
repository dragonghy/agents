import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { fetchTickets, batchArchiveTickets } from '../api/tickets';
import { fetchAgents } from '../api/agents';
import type { Ticket } from '../types/ticket';
import type { Agent } from '../types/agent';

const STATUS_LABELS: Record<number, string> = {
  3: 'New',
  4: 'In Progress',
  1: 'Blocked',
  0: 'Done',
  '-1': 'Archived',
};

const STATUS_COLORS: Record<number, string> = {
  3: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  4: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  1: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  0: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  '-1': 'bg-gray-50 text-gray-400 dark:bg-gray-800 dark:text-gray-500',
};

/* ── Time filter helpers ── */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

const TIME_FILTERS: { label: string; value: string }[] = [
  { label: 'All time', value: '' },
  { label: 'Today', value: '0' },
  { label: 'Last 7 days', value: '7' },
  { label: 'Last 30 days', value: '30' },
];

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

export default function Tickets() {
  const navigate = useNavigate();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  /* Item 2: "All Tickets" excludes archived; separate "Archived" option */
  const [statusFilter, setStatusFilter] = useState('0,1,3,4');
  /* Item 1: Time filter */
  const [timeFilter, setTimeFilter] = useState('');
  /* Item 3: Batch selection */
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [archiving, setArchiving] = useState(false);
  /* Shift-click range selection */
  const [lastClickedIdx, setLastClickedIdx] = useState<number | null>(null);

  // New ticket modal
  const [showModal, setShowModal] = useState(false);
  const [newHeadline, setNewHeadline] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newAssignee, setNewAssignee] = useState('');
  const [newPriority, setNewPriority] = useState('');
  const [newStartTime, setNewStartTime] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setSelected(new Set());

    async function load() {
      try {
        const params: Record<string, string> = { status: statusFilter };
        if (timeFilter) {
          params.dateFrom = daysAgo(Number(timeFilter));
        }
        const data = await fetchTickets(params);
        if (active) {
          setTickets(data.tickets);
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    return () => { active = false; };
  }, [statusFilter, timeFilter]);

  function toggleSelect(id: number, index: number, shiftKey: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);

      if (shiftKey && lastClickedIdx !== null) {
        // Shift-click: select range between lastClickedIdx and current index
        const start = Math.min(lastClickedIdx, index);
        const end = Math.max(lastClickedIdx, index);
        for (let i = start; i <= end; i++) {
          next.add(tickets[i].id);
        }
      } else {
        if (next.has(id)) next.delete(id);
        else next.add(id);
      }

      return next;
    });
    setLastClickedIdx(index);
  }

  function toggleSelectAll() {
    if (selected.size === tickets.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(tickets.map((t) => t.id)));
    }
  }

  async function handleBatchArchive() {
    if (selected.size === 0) return;
    if (!confirm(`Archive ${selected.size} ticket(s)?`)) return;
    setArchiving(true);
    try {
      await batchArchiveTickets([...selected]);
      setSelected(new Set());
      // Reload
      const params: Record<string, string> = { status: statusFilter };
      if (timeFilter) params.dateFrom = daysAgo(Number(timeFilter));
      const data = await fetchTickets(params);
      setTickets(data.tickets);
    } catch (e) {
      setError(String(e));
    } finally {
      setArchiving(false);
    }
  }

  async function handleCreateTicket() {
    if (!newHeadline.trim()) return;
    setCreating(true);
    try {
      const body: Record<string, unknown> = { headline: newHeadline };
      if (newDescription) body.description = newDescription;
      if (newAssignee) body.assignee = newAssignee;
      if (newPriority) body.priority = newPriority;
      if (newStartTime) body.start_time = newStartTime.replace('T', ' ') + ':00';

      const res = await fetch('/api/v1/tickets/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setShowModal(false);
      setNewHeadline('');
      setNewDescription('');
      setNewAssignee('');
      setNewPriority('');
      if (data.ticket_id) {
        navigate(`/tickets/${data.ticket_id}`);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-9 w-48" />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4 space-y-3">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      </div>
    );
  }

  if (error) return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Tickets</h2>
        <div className="flex flex-wrap gap-2">
          {/* Item 1: Time filter */}
          <select
            value={timeFilter}
            onChange={(e) => setTimeFilter(e.target.value)}
            className="text-sm border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
          >
            {TIME_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
          {/* Item 2: Status filter with separated "Archived" */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
          >
            <option value="1,3,4">Active (New + In Progress + Blocked)</option>
            <option value="3,4">New + In Progress</option>
            <option value="0,1,3,4">All Tickets</option>
            <option value="0">Done</option>
            <option value="-1">Archived</option>
          </select>
          {/* Item 3: Batch archive button */}
          {selected.size > 0 && (
            <button
              onClick={handleBatchArchive}
              disabled={archiving}
              className="px-3 py-1.5 bg-gray-600 text-white rounded text-sm font-medium hover:bg-gray-700 disabled:opacity-50"
            >
              {archiving ? 'Archiving...' : `Archive (${selected.size})`}
            </button>
          )}
          <button
            onClick={() => setShowModal(true)}
            className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
          >
            New Ticket
          </button>
        </div>
      </div>

      {/* New Ticket Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-lg p-6 mx-4">
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-4">Create Ticket</h3>
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Title *</label>
                <input
                  type="text"
                  value={newHeadline}
                  onChange={(e) => setNewHeadline(e.target.value)}
                  className="mt-1 w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Ticket headline"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Description</label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  rows={4}
                  className="mt-1 w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                  placeholder="Markdown supported..."
                />
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Assignee</label>
                  <select
                    value={newAssignee}
                    onChange={(e) => setNewAssignee(e.target.value)}
                    className="mt-1 w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
                  >
                    <option value="">None</option>
                    {agents.map((a) => <option key={a.id} value={a.id}>{a.id}</option>)}
                  </select>
                </div>
                <div className="flex-1">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Priority</label>
                  <select
                    value={newPriority}
                    onChange={(e) => setNewPriority(e.target.value)}
                    className="mt-1 w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
                  >
                    <option value="">Default</option>
                    <option value="urgent">Urgent</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Start Time (optional, for scheduled tasks)</label>
                <input
                  type="datetime-local"
                  value={newStartTime}
                  onChange={(e) => setNewStartTime(e.target.value)}
                  className="mt-1 w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateTicket}
                disabled={!newHeadline.trim() || creating}
                className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            <tr>
              {/* Checkbox column — larger click target */}
              <th className="w-12 px-2 py-3">
                <label className="flex items-center justify-center w-8 h-8 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={tickets.length > 0 && selected.size === tickets.length}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500"
                  />
                </label>
              </th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">ID</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Title</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Status</th>
              {/* Item 10: Assignee column */}
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Assignee</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300 hidden sm:table-cell">Priority</th>
              {/* Item 4: Full timestamp */}
              <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-300 hidden sm:table-cell">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {tickets.map((ticket, idx) => (
              <tr key={ticket.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <td className="px-2 py-3">
                  <label className="flex items-center justify-center w-8 h-8 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selected.has(ticket.id)}
                      onClick={(e) => toggleSelect(ticket.id, idx, e.shiftKey)}
                      onChange={() => {}}
                      className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                  </label>
                </td>
                <td className="px-4 py-3">
                  <Link to={`/tickets/${ticket.id}`} className="text-blue-600 dark:text-blue-400 hover:underline">
                    #{ticket.id}
                  </Link>
                </td>
                <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                  <Link to={`/tickets/${ticket.id}`} className="hover:underline">
                    {ticket.headline}
                  </Link>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[ticket.status] || 'bg-gray-100 dark:bg-gray-800'}`}>
                    {STATUS_LABELS[ticket.status] || ticket.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                  {ticket.assignee ? (
                    <Link to={`/agents/${ticket.assignee}`} className="text-blue-600 dark:text-blue-400 hover:underline">
                      {ticket.assignee}
                    </Link>
                  ) : '-'}
                </td>
                <td className="px-4 py-3 text-gray-600 dark:text-gray-400 hidden sm:table-cell">{ticket.priority || '-'}</td>
                {/* Item 4: Full timestamp with time */}
                <td className="px-4 py-3 text-gray-500 dark:text-gray-400 hidden sm:table-cell whitespace-nowrap">
                  {ticket.date || '-'}
                </td>
              </tr>
            ))}
            {tickets.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-400 dark:text-gray-500">No tickets found</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
