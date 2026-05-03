/**
 * TicketDetail — drill-in view for a single ticket (Task #20 Finding #2).
 *
 * Shows:
 * - Header: id, headline, status badge (with edit dropdown), priority, workspace,
 *   project, assignee, tags
 * - Dependencies: small "Depends on" / "Required by" sections
 * - Comments: read-only list (authoring deferred)
 * - Sessions bound to this ticket: TPM first (parent_session_id IS NULL +
 *   profile_name='tpm'), then descendants. Each row links to /sessions/:id.
 *
 * Read-only mutations supported in v1: status, priority, headline only.
 * Comment authoring + ticket creation are out of scope.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getTicketComments,
  getTicketDetail,
  getTicketSessions,
  patchTicket,
} from '../api';
import type {
  Session,
  TicketComment,
  TicketDetail as TicketDetailType,
} from '../types';

const STATUS_OPTIONS: { value: number; label: string }[] = [
  { value: 3, label: '3 — New' },
  { value: 4, label: '4 — In Progress' },
  { value: 1, label: '1 — Blocked' },
  { value: 0, label: '0 — Done' },
  { value: -1, label: '-1 — Archived' },
];

const STATUS_LABEL: Record<number, string> = {
  4: 'IN PROGRESS',
  3: 'NEW',
  1: 'BLOCKED',
  0: 'DONE',
  [-1]: 'ARCHIVED',
};
const STATUS_COLOR: Record<number, string> = {
  4: '#facc15',
  3: '#60a5fa',
  1: '#f87171',
  0: '#94a3b8',
  [-1]: '#64748b',
};

export default function TicketDetail() {
  const { id } = useParams<{ id: string }>();
  const ticketId = Number(id || '0');
  const [ticket, setTicket] = useState<TicketDetailType | null>(null);
  const [comments, setComments] = useState<TicketComment[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!Number.isFinite(ticketId) || ticketId <= 0) {
      setError(`Invalid ticket id: ${id}`);
      setLoading(false);
      return;
    }
    try {
      const [t, c, s] = await Promise.all([
        getTicketDetail(ticketId),
        getTicketComments(ticketId).catch((e) => {
          console.warn('comments fetch failed:', e);
          return { comments: [] as TicketComment[], total: 0 };
        }),
        getTicketSessions(ticketId).catch((e) => {
          console.warn('sessions fetch failed:', e);
          return { sessions: [] as Session[], total: 0, ticket_id: ticketId };
        }),
      ]);
      setTicket(t);
      setComments(c.comments);
      setSessions(s.sessions);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [ticketId, id]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function onChangeStatus(newStatus: number) {
    if (!ticket || busy) return;
    setBusy(true);
    try {
      await patchTicket(ticket.id, { status: newStatus });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (loading && !ticket) return <p className="loading">Loading ticket…</p>;
  if (error && !ticket) {
    return (
      <div>
        <div className="error">{error}</div>
        <p>
          <Link to="/board">← back to Tickets</Link>
        </p>
      </div>
    );
  }
  if (!ticket) {
    return (
      <div>
        <div className="error">Ticket not found.</div>
        <p>
          <Link to="/board">← back to Tickets</Link>
        </p>
      </div>
    );
  }

  // Sort sessions: TPM root first (parent_session_id null + profile=tpm), then others by created_at desc.
  const sortedSessions = [...sessions].sort((a, b) => {
    const aIsTpm =
      a.parent_session_id == null && a.profile_name === 'tpm' ? 0 : 1;
    const bIsTpm =
      b.parent_session_id == null && b.profile_name === 'tpm' ? 0 : 1;
    if (aIsTpm !== bIsTpm) return aIsTpm - bIsTpm;
    return (b.created_at || '').localeCompare(a.created_at || '');
  });

  const status = ticket.status ?? 0;
  const statusLabel = STATUS_LABEL[status] || String(status);
  const statusColor = STATUS_COLOR[status] || 'var(--text-muted)';

  return (
    <div>
      <div className="page-header">
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <code style={{ fontSize: 16, color: 'var(--text-dim)' }}>#{ticket.id}</code>
          <span>{ticket.headline}</span>
        </h2>
        <span className="subtitle">
          <Link to="/board">← all tickets</Link>
        </span>
      </div>

      {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}

      {/* Metadata + status edit */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="grid grid-3">
          <Meta
            label="Status"
            value={
              <span style={{ color: statusColor, fontWeight: 600 }}>{statusLabel}</span>
            }
          />
          <Meta label="Priority" value={ticket.priority || '—'} />
          <Meta label="Type" value={ticket.type || '—'} />
          <Meta
            label="Workspace"
            value={
              ticket.workspace_name
                ? `${ticket.workspace_name} (#${ticket.workspace_id})`
                : ticket.workspace_id != null
                ? `#${ticket.workspace_id}`
                : '—'
            }
          />
          <Meta
            label="Project"
            value={
              ticket.project_name
                ? `${ticket.project_name} (#${ticket.projectId})`
                : ticket.projectId != null
                ? `#${ticket.projectId}`
                : '—'
            }
          />
          <Meta label="Assignee" value={ticket.assignee || 'unassigned'} />
        </div>
        <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Change status:&nbsp;
            <select
              value={status}
              onChange={(e) => onChangeStatus(Number(e.target.value))}
              disabled={busy}
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          {ticket.tags && (
            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              tags: {ticket.tags}
            </span>
          )}
        </div>
      </div>

      {/* Dependencies */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Dependencies</h3>
        <div className="grid grid-2">
          <DepList
            label="Depends on"
            items={ticket.dependencies?.depends_on || []}
          />
          <DepList
            label="Required by"
            items={ticket.dependencies?.dependents || []}
          />
        </div>
      </div>

      {/* Sessions */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0, display: 'flex', alignItems: 'center' }}>
          Sessions
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
            {sortedSessions.length} total
          </span>
        </h3>
        {sortedSessions.length === 0 ? (
          <div className="empty-state">No sessions bound to this ticket.</div>
        ) : (
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Session</th>
                <th style={thStyle}>Profile</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Parent</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Tokens</th>
                <th style={thStyle}>Created</th>
              </tr>
            </thead>
            <tbody>
              {sortedSessions.map((s) => {
                const isTpm =
                  s.parent_session_id == null && s.profile_name === 'tpm';
                return (
                  <tr
                    key={s.id}
                    style={{
                      background: isTpm ? 'var(--bg-panel-hover)' : undefined,
                    }}
                  >
                    <td style={tdStyle}>
                      <Link
                        to={`/sessions/${encodeURIComponent(s.id)}`}
                        style={{ color: 'var(--text)', textDecoration: 'underline' }}
                      >
                        <code style={{ fontSize: 11 }}>{s.id}</code>
                      </Link>
                      {isTpm && (
                        <span
                          style={{
                            marginLeft: 6,
                            fontSize: 10,
                            color: '#4ade80',
                            border: '1px solid #4ade80',
                            borderRadius: 3,
                            padding: '0 4px',
                          }}
                        >
                          TPM
                        </span>
                      )}
                    </td>
                    <td style={tdStyle}>{s.profile_name}</td>
                    <td style={tdStyle}>{s.status}</td>
                    <td style={tdStyle}>
                      {s.parent_session_id ? (
                        <code style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                          {s.parent_session_id}
                        </code>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td
                      style={{
                        ...tdStyle,
                        textAlign: 'right',
                        fontFamily: 'monospace',
                        fontSize: 11,
                      }}
                    >
                      {(s.cost_tokens_in || 0).toLocaleString()} /{' '}
                      {(s.cost_tokens_out || 0).toLocaleString()}
                    </td>
                    <td style={tdStyle}>{(s.created_at || '').slice(0, 16)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Comments */}
      <div className="card">
        <h3 style={{ marginTop: 0, display: 'flex', alignItems: 'center' }}>
          Comments
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
            {comments.length} total
          </span>
        </h3>
        {comments.length === 0 ? (
          <div className="empty-state">No comments yet.</div>
        ) : (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              maxHeight: 480,
              overflowY: 'auto',
            }}
          >
            {comments.map((c) => (
              <div
                key={c.id}
                style={{
                  background: 'var(--bg-panel)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: 8,
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    color: 'var(--text-muted)',
                    marginBottom: 4,
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{c.author || 'unknown'}</span>
                  <span> · </span>
                  <span>{(c.date || '').slice(0, 19)}</span>
                </div>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{c.text}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 13 }}>{value}</div>
    </div>
  );
}

function DepList({
  label,
  items,
}: {
  label: string;
  items: { id: number; headline: string | null; status: number | null }[];
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          marginBottom: 4,
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      {items.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>none</div>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {items.map((d) => (
            <li key={d.id} style={{ marginBottom: 2 }}>
              <Link
                to={`/tickets/${d.id}`}
                style={{ color: 'var(--text)', fontSize: 12 }}
              >
                <code style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  #{d.id}
                </code>{' '}
                {d.headline || '(no headline)'}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
};
const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 8px',
  borderBottom: '1px solid var(--border)',
  color: 'var(--text-dim)',
  fontWeight: 600,
  fontSize: 11,
  textTransform: 'uppercase',
};
const tdStyle: React.CSSProperties = {
  padding: '6px 8px',
  borderBottom: '1px solid var(--border)',
};
