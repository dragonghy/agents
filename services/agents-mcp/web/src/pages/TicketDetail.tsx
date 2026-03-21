import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchTicket, fetchTicketComments, fetchTicketSubtasks } from '../api/tickets';
import { fetchAgents } from '../api/agents';
import type { Ticket, TicketComment, Subtask } from '../types/ticket';
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

/* Item 4: Full timestamp (date + time) */
function formatDateTime(dateStr: string): string {
  if (!dateStr || dateStr === '0000-00-00 00:00:00') return '-';
  return dateStr;
}

/* Item 9: Comment author display */
function formatAuthor(comment: TicketComment): string {
  if (comment.author) return comment.author;
  if (comment.userId === 1) return 'Human';
  return `User #${comment.userId}`;
}

/* Item 6: Copy markdown to clipboard */
async function copyMarkdown(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Fallback for older browsers
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

function CopyButton({ text, label = 'Copy Markdown' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await copyMarkdown(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="text-xs px-2 py-1 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-50 dark:hover:bg-gray-800"
    >
      {copied ? 'Copied!' : label}
    </button>
  );
}

/* Item 7: Markdown with GFM tables + Item 8: image support */
function MarkdownContent({ children }: { children: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Item 8: render images
        img: ({ src, alt, ...props }) => (
          <img
            src={src}
            alt={alt || ''}
            className="max-w-full rounded border border-gray-200 dark:border-gray-700 my-2"
            loading="lazy"
            {...props}
          />
        ),
      }}
    >
      {children}
    </Markdown>
  );
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

export default function TicketDetail() {
  const { id } = useParams<{ id: string }>();
  const ticketId = Number(id);

  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [comments, setComments] = useState<TicketComment[]>([]);
  const [commentsTotal, setCommentsTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newComment, setNewComment] = useState('');
  const [submittingComment, setSubmittingComment] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [reassignTo, setReassignTo] = useState('');
  const [reassignComment, setReassignComment] = useState('');
  const [reassigning, setReassigning] = useState(false);
  const [showReassign, setShowReassign] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents().then(setAgents).catch(() => {});
  }, []);

  async function loadTicketData() {
    try {
      const [t, cResp, s] = await Promise.all([
        fetchTicket(ticketId),
        fetchTicketComments(ticketId, 10, 0),
        fetchTicketSubtasks(ticketId),
      ]);
      setTicket(t);
      setComments(cResp.comments);
      setCommentsTotal(cResp.total);
      setSubtasks(s);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadMoreComments() {
    setLoadingMore(true);
    try {
      const resp = await fetchTicketComments(ticketId, 10, comments.length);
      setComments(prev => [...prev, ...resp.comments]);
    } catch (e) {
      setActionMsg(`Error loading more: ${e}`);
    } finally {
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    let active = true;
    async function load() {
      await loadTicketData();
      if (active) setLoading(false);
    }
    load();
    return () => { active = false; };
  }, [ticketId]);

  async function handleAddComment() {
    if (!newComment.trim()) return;
    setSubmittingComment(true);
    try {
      await fetch(`/api/v1/tickets/${ticketId}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comment: newComment, author: 'Human' }),
      });
      setNewComment('');
      setActionMsg('Comment added');
      await loadTicketData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e) {
      setActionMsg(`Error: ${e}`);
    } finally {
      setSubmittingComment(false);
    }
  }

  async function handleStatusChange(newStatus: number) {
    setUpdatingStatus(true);
    try {
      await fetch(`/api/v1/tickets/${ticketId}/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      setActionMsg(`Status changed to ${STATUS_LABELS[newStatus] || newStatus}`);
      await loadTicketData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e) {
      setActionMsg(`Error: ${e}`);
    } finally {
      setUpdatingStatus(false);
    }
  }

  async function handleReassign() {
    if (!reassignTo) return;
    setReassigning(true);
    try {
      await fetch(`/api/v1/tickets/${ticketId}/reassign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_agent: ticket?.assignee || 'human',
          to_agent: reassignTo,
          comment: reassignComment || undefined,
        }),
      });
      setActionMsg(`Reassigned to ${reassignTo}`);
      setShowReassign(false);
      setReassignTo('');
      setReassignComment('');
      await loadTicketData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e) {
      setActionMsg(`Error: ${e}`);
    } finally {
      setReassigning(false);
    }
  }

  /* Item 10: Direct assignee change */
  async function handleAssigneeChange(newAssignee: string) {
    try {
      await fetch(`/api/v1/tickets/${ticketId}/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assignee: newAssignee || null }),
      });
      setActionMsg(`Assignee updated to ${newAssignee || 'none'}`);
      await loadTicketData();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e) {
      setActionMsg(`Error: ${e}`);
    }
  }

  if (loading) {
    return (
      <div>
        <Skeleton className="h-4 w-24 mb-4" />
        <Skeleton className="h-8 w-2/3 mb-4" />
        <div className="flex gap-6">
          <div className="flex-1"><Skeleton className="h-48 w-full" /></div>
          <div className="w-64"><Skeleton className="h-48 w-full" /></div>
        </div>
      </div>
    );
  }

  if (error) return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;
  if (!ticket) return <div className="text-red-600 dark:text-red-400">Ticket not found</div>;

  return (
    <div>
      <div className="mb-4">
        <Link to="/tickets" className="text-blue-600 dark:text-blue-400 hover:underline text-sm">&larr; Back to Tickets</Link>
      </div>

      {actionMsg && (
        <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded text-sm text-green-800 dark:text-green-300">
          {actionMsg}
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Main content */}
        <div className="flex-1 min-w-0">
          <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-1">
            <span className="text-gray-400 dark:text-gray-500">#{ticket.id}</span> {ticket.headline}
          </h2>

          {/* Item 6: Copy Markdown button for description */}
          {ticket.description && (
            <div className="mt-4">
              <div className="flex justify-end mb-1">
                <CopyButton text={ticket.description} />
              </div>
              <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-5 prose prose-sm dark:prose-invert max-w-none">
                {/* Item 7: GFM tables + Item 8: images */}
                <MarkdownContent>{ticket.description}</MarkdownContent>
              </div>
            </div>
          )}

          {subtasks.length > 0 && (
            <div className="mt-6">
              <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-3">Subtasks</h3>
              <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                    <tr>
                      <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">ID</th>
                      <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">Title</th>
                      <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-300">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {subtasks.map((st) => (
                      <tr key={st.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                        <td className="px-4 py-2 text-gray-500 dark:text-gray-400">#{st.id}</td>
                        <td className="px-4 py-2 text-gray-900 dark:text-gray-100">{st.headline}</td>
                        <td className="px-4 py-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            STATUS_COLORS[Number(st.status)] || 'bg-gray-100 dark:bg-gray-800'
                          }`}>
                            {STATUS_LABELS[Number(st.status)] || st.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Comments */}
          <div className="mt-6">
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-3">
              Comments ({comments.length}{commentsTotal > comments.length ? ` of ${commentsTotal}` : ''})
            </h3>

            {/* Item 5: Add Comment at TOP */}
            <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4 mb-4">
              <textarea
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                placeholder="Add a comment (Markdown supported, images via ![alt](url))..."
                rows={3}
                className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y placeholder-gray-400 dark:placeholder-gray-500"
              />
              <div className="flex justify-end mt-2">
                <button
                  onClick={handleAddComment}
                  disabled={!newComment.trim() || submittingComment}
                  className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {submittingComment ? 'Adding...' : 'Add Comment'}
                </button>
              </div>
            </div>

            {comments.length === 0 ? (
              <div className="text-gray-400 dark:text-gray-500 text-sm">No comments yet</div>
            ) : (
              <div className="space-y-3">
                {comments.map((comment) => (
                  <div key={comment.id} className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
                    <div className="flex items-center justify-between mb-2">
                      {/* Item 9: Show author name or "Human" */}
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        {formatAuthor(comment)}
                      </span>
                      <div className="flex items-center gap-2">
                        {/* Item 6: Copy button for comment */}
                        <CopyButton text={comment.text} label="Copy" />
                        {/* Item 4: Full timestamp */}
                        <span className="text-xs text-gray-400 dark:text-gray-500">{formatDateTime(comment.date)}</span>
                      </div>
                    </div>
                    <div className="text-sm text-gray-800 dark:text-gray-200 prose prose-sm dark:prose-invert max-w-none">
                      {/* Item 7: GFM tables + Item 8: images */}
                      <MarkdownContent>{comment.text}</MarkdownContent>
                    </div>
                  </div>
                ))}
                {commentsTotal > comments.length && (
                  <button
                    onClick={loadMoreComments}
                    disabled={loadingMore}
                    className="w-full py-2 text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                  >
                    {loadingMore ? 'Loading...' : `Load more (${commentsTotal - comments.length} remaining)`}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="w-full lg:w-64 flex-shrink-0">
          <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4 space-y-4 sticky top-6">
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</label>
              <div className="mt-1">
                <select
                  value={ticket.status}
                  onChange={(e) => handleStatusChange(Number(e.target.value))}
                  disabled={updatingStatus}
                  className="w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
                >
                  {Object.entries(STATUS_LABELS).map(([val, label]) => (
                    <option key={val} value={val}>{label}</option>
                  ))}
                </select>
              </div>
            </div>
            {/* Item 10: Assignee as independent editable field */}
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Assignee</label>
              <select
                value={ticket.assignee || ''}
                onChange={(e) => handleAssigneeChange(e.target.value)}
                className="mt-1 w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
              >
                <option value="">Unassigned</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>{a.id}</option>
                ))}
              </select>
              <button
                onClick={() => setShowReassign(!showReassign)}
                className="mt-1 text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                {showReassign ? 'Cancel' : 'Reassign (with note)'}
              </button>
              {showReassign && (
                <div className="mt-2 space-y-2">
                  <select
                    value={reassignTo}
                    onChange={(e) => setReassignTo(e.target.value)}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
                  >
                    <option value="">Select agent...</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>{a.id}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={reassignComment}
                    onChange={(e) => setReassignComment(e.target.value)}
                    placeholder="Handoff note (optional)"
                    className="w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500"
                  />
                  <button
                    onClick={handleReassign}
                    disabled={!reassignTo || reassigning}
                    className="w-full px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
                  >
                    {reassigning ? 'Reassigning...' : 'Reassign'}
                  </button>
                </div>
              )}
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Priority</label>
              <p className="mt-1 text-sm text-gray-800 dark:text-gray-200">{ticket.priority || '-'}</p>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Type</label>
              <p className="mt-1 text-sm text-gray-800 dark:text-gray-200">{ticket.type || '-'}</p>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Project ID</label>
              <p className="mt-1 text-sm text-gray-800 dark:text-gray-200">{ticket.projectId}</p>
            </div>
            <div>
              {/* Item 4: Full timestamp */}
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Created</label>
              <p className="mt-1 text-sm text-gray-800 dark:text-gray-200">{formatDateTime(ticket.date)}</p>
            </div>
            {ticket.start_time && ticket.start_time !== '' && ticket.start_time !== '0000-00-00 00:00:00' && (
              <div>
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Scheduled Start</label>
                <p className="mt-1 text-sm text-orange-600 dark:text-orange-400">{formatDateTime(ticket.start_time)}</p>
              </div>
            )}
            {ticket.tags && (
              <div>
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Tags</label>
                <div className="mt-1 flex flex-wrap gap-1">
                  {ticket.tags.split(',').map((tag) => (
                    <span key={tag} className="px-2 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded text-xs">
                      {tag.trim()}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
