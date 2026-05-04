/**
 * TicketDetail — drill-in view for a single ticket.
 *
 * Now actually editable (Wave 2 — Human review 2026-05-04):
 * - Inline headline edit (click → input + save/cancel)
 * - Description rendered as markdown-ish text + collapsed editor
 * - Comment composer at the bottom (POST /tickets/{id}/comments)
 * - Sessions list with TPM badge + click-through
 * - Status / priority / assignee inline editors
 *
 * SSE-aware: ticket-comment events for THIS ticket trigger a refresh
 * so a comment posted from another tab shows up live.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  addTicketComment,
  getTicketComments,
  getTicketDetail,
  getTicketSessions,
  patchTicket,
} from '../api';
import { sseBus } from '../lib/sseBus';
import type {
  Session,
  TicketComment,
  TicketDetail as TicketDetailType,
} from '../types';

const STATUS_OPTIONS: { value: number; label: string; color: string }[] = [
  { value: 3, label: 'New', color: '#60a5fa' },
  { value: 4, label: 'In Progress', color: '#facc15' },
  { value: 1, label: 'Blocked', color: '#f87171' },
  { value: 0, label: 'Done', color: '#4ade80' },
  { value: -1, label: 'Archived', color: '#64748b' },
];

const PRIORITY_OPTIONS = ['urgent', 'high', 'medium', 'low'];

export default function TicketDetail() {
  const { id } = useParams<{ id: string }>();
  const ticketId = Number(id || '0');
  const [ticket, setTicket] = useState<TicketDetailType | null>(null);
  const [comments, setComments] = useState<TicketComment[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Edit modes
  const [editingHeadline, setEditingHeadline] = useState(false);
  const [headlineDraft, setHeadlineDraft] = useState('');
  const [editingDesc, setEditingDesc] = useState(false);
  const [descDraft, setDescDraft] = useState('');
  const [editingAssignee, setEditingAssignee] = useState(false);
  const [assigneeDraft, setAssigneeDraft] = useState('');

  // Comment composer
  const [commentDraft, setCommentDraft] = useState('');
  const [commenting, setCommenting] = useState(false);

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

  // SSE: refresh on session events bound to this ticket so the bound
  // sessions list stays live.
  useEffect(() => {
    if (!ticketId) return;
    const handler = () => {
      // Cheap: refresh ticket + sessions; debounced naturally by the
      // 250ms minimum between SSE events on a single ticket.
      refresh();
    };
    const offCreated = sseBus.subscribe('session.created', handler);
    const offClosed = sseBus.subscribe('session.closed', handler);
    return () => {
      offCreated();
      offClosed();
    };
  }, [ticketId, refresh]);

  async function patch(body: Parameters<typeof patchTicket>[1]) {
    if (!ticket || busy) return;
    setBusy(true);
    setError(null);
    try {
      await patchTicket(ticket.id, body);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onPostComment() {
    const body = commentDraft.trim();
    if (!body || !ticket || commenting) return;
    setCommenting(true);
    setError(null);
    try {
      await addTicketComment(ticket.id, body);
      setCommentDraft('');
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setCommenting(false);
    }
  }

  function startHeadlineEdit() {
    if (!ticket) return;
    setHeadlineDraft(ticket.headline || '');
    setEditingHeadline(true);
  }
  async function saveHeadline() {
    const next = headlineDraft.trim();
    if (!next || next === ticket?.headline) {
      setEditingHeadline(false);
      return;
    }
    await patch({ headline: next });
    setEditingHeadline(false);
  }

  function startDescEdit() {
    if (!ticket) return;
    setDescDraft(ticket.description || '');
    setEditingDesc(true);
  }
  async function saveDesc() {
    if (descDraft === (ticket?.description || '')) {
      setEditingDesc(false);
      return;
    }
    await patch({ description: descDraft });
    setEditingDesc(false);
  }

  function startAssigneeEdit() {
    if (!ticket) return;
    setAssigneeDraft(ticket.assignee || '');
    setEditingAssignee(true);
  }
  async function saveAssignee() {
    if (assigneeDraft.trim() === (ticket?.assignee || '')) {
      setEditingAssignee(false);
      return;
    }
    await patch({ assignee: assigneeDraft.trim() });
    setEditingAssignee(false);
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

  // Sessions: TPM root first, then children by created_at desc.
  const sortedSessions = [...sessions].sort((a, b) => {
    const aIsTpm =
      a.parent_session_id == null && a.profile_name === 'tpm' ? 0 : 1;
    const bIsTpm =
      b.parent_session_id == null && b.profile_name === 'tpm' ? 0 : 1;
    if (aIsTpm !== bIsTpm) return aIsTpm - bIsTpm;
    return (b.created_at || '').localeCompare(a.created_at || '');
  });

  const status = ticket.status ?? 0;
  const statusOpt =
    STATUS_OPTIONS.find((o) => o.value === status) || STATUS_OPTIONS[0];

  return (
    <div className="ticket-detail">
      {/* Breadcrumb + back */}
      <div className="page-header">
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
          <code style={{ fontSize: 16, color: 'var(--text-dim)' }}>#{ticket.id}</code>
          {editingHeadline ? (
            <span style={{ display: 'flex', gap: 6, alignItems: 'center', flex: 1 }}>
              <input
                value={headlineDraft}
                onChange={(e) => setHeadlineDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveHeadline();
                  if (e.key === 'Escape') setEditingHeadline(false);
                }}
                autoFocus
                disabled={busy}
                className="inline-input inline-input-large"
              />
              <button onClick={saveHeadline} disabled={busy} className="btn-primary btn-sm">
                Save
              </button>
              <button onClick={() => setEditingHeadline(false)} disabled={busy} className="btn-secondary btn-sm">
                Cancel
              </button>
            </span>
          ) : (
            <span
              onClick={startHeadlineEdit}
              className="editable-heading"
              title="click to edit"
            >
              {ticket.headline || <em style={{ color: 'var(--text-muted)' }}>no headline</em>}
            </span>
          )}
        </h2>
        <span className="subtitle">
          <Link to="/board">← all tickets</Link>
        </span>
      </div>

      {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}

      {/* Status chip row + inline metadata edit */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="metadata-row">
          <StatusPill status={status} onChange={(v) => patch({ status: v })} disabled={busy} />
          <PriorityPill
            priority={ticket.priority || 'medium'}
            onChange={(v) => patch({ priority: v })}
            disabled={busy}
          />
          <Pill label="Type" value={ticket.type || '—'} muted />
          <Pill
            label="Workspace"
            value={
              ticket.workspace_name
                ? `${ticket.workspace_name}`
                : ticket.workspace_id != null
                ? `#${ticket.workspace_id}`
                : '—'
            }
            muted
          />
          <Pill
            label="Project"
            value={
              ticket.project_name
                ? `${ticket.project_name}`
                : ticket.projectId != null
                ? `#${ticket.projectId}`
                : '—'
            }
            muted
          />
          <div className="pill-group">
            <span className="pill-label">Assignee</span>
            {editingAssignee ? (
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input
                  value={assigneeDraft}
                  onChange={(e) => setAssigneeDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveAssignee();
                    if (e.key === 'Escape') setEditingAssignee(false);
                  }}
                  autoFocus
                  disabled={busy}
                  placeholder="(empty for unassigned)"
                  className="inline-input"
                  style={{ width: 140 }}
                />
                <button onClick={saveAssignee} disabled={busy} className="btn-primary btn-sm">
                  Save
                </button>
                <button onClick={() => setEditingAssignee(false)} disabled={busy} className="btn-secondary btn-sm">
                  ✕
                </button>
              </span>
            ) : (
              <span
                onClick={startAssigneeEdit}
                className="pill-value editable"
                title="click to edit"
              >
                {ticket.assignee || <em style={{ color: 'var(--text-muted)' }}>unassigned</em>}
              </span>
            )}
          </div>
        </div>

        {ticket.tags && (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-dim)' }}>
            <span style={{ marginRight: 6, color: 'var(--text-muted)' }}>tags:</span>
            {ticket.tags.split(',').map((tag, i) => (
              <span key={i} className="tag">
                {tag.trim()}
              </span>
            ))}
          </div>
        )}
        {/* status legend chip color reference */}
        <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-muted)' }}>
          Status: <span style={{ color: statusOpt.color, fontWeight: 600 }}>{statusOpt.label.toUpperCase()}</span>
        </div>
      </div>

      {/* Description */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Description</h3>
          {!editingDesc && (
            <button onClick={startDescEdit} className="btn-secondary btn-sm" style={{ marginLeft: 'auto' }}>
              Edit
            </button>
          )}
        </div>
        {editingDesc ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              value={descDraft}
              onChange={(e) => setDescDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                  e.preventDefault();
                  saveDesc();
                }
                if (e.key === 'Escape') setEditingDesc(false);
              }}
              disabled={busy}
              rows={8}
              placeholder="What's this ticket about? Markdown supported, plain text rendered as-is."
              className="composer-textarea"
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={saveDesc} disabled={busy} className="btn-primary btn-sm">
                {busy ? 'Saving…' : 'Save (⌘+Enter)'}
              </button>
              <button onClick={() => setEditingDesc(false)} disabled={busy} className="btn-secondary btn-sm">
                Cancel
              </button>
            </div>
          </div>
        ) : ticket.description ? (
          <div className="ticket-description">{ticket.description}</div>
        ) : (
          <div className="empty-state" style={{ padding: 16 }}>
            <em>No description.</em>{' '}
            <button onClick={startDescEdit} className="btn-secondary btn-sm" style={{ marginLeft: 8 }}>
              Add one
            </button>
          </div>
        )}
      </div>

      {/* Dependencies */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Dependencies</h3>
        <div className="grid grid-2">
          <DepList label="Depends on" items={ticket.dependencies?.depends_on || []} />
          <DepList label="Required by" items={ticket.dependencies?.dependents || []} />
        </div>
      </div>

      {/* Sessions */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0, display: 'flex', alignItems: 'center' }}>
          Bound sessions
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
            {sortedSessions.length} total
          </span>
        </h3>
        {sortedSessions.length === 0 ? (
          <div className="empty-state">No sessions bound to this ticket.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Profile</th>
                <th>Status</th>
                <th>Parent</th>
                <th style={{ textAlign: 'right' }}>Tokens (in / out)</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {sortedSessions.map((s) => {
                const isTpm =
                  s.parent_session_id == null && s.profile_name === 'tpm';
                return (
                  <tr key={s.id} className={isTpm ? 'data-row-tpm' : ''}>
                    <td>
                      <Link
                        to={`/sessions/${encodeURIComponent(s.id)}`}
                        className="session-link"
                      >
                        <code>{s.id}</code>
                      </Link>
                      {isTpm && <span className="tpm-badge">TPM</span>}
                    </td>
                    <td>{s.profile_name}</td>
                    <td>
                      <span className={`session-status status-${s.status}`}>{s.status}</span>
                    </td>
                    <td>
                      {s.parent_session_id ? (
                        <Link
                          to={`/sessions/${encodeURIComponent(s.parent_session_id)}`}
                          className="session-link-dim"
                        >
                          <code>{s.parent_session_id.slice(0, 16)}…</code>
                        </Link>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: 11 }}>
                      {(s.cost_tokens_in || 0).toLocaleString()} /{' '}
                      {(s.cost_tokens_out || 0).toLocaleString()}
                    </td>
                    <td>{(s.created_at || '').slice(0, 16)}</td>
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
          <div className="empty-state">No comments yet — be the first.</div>
        ) : (
          <div className="comments-list">
            {comments.map((c) => (
              <div key={c.id} className="comment">
                <div className="comment-meta">
                  <span className="comment-author">{c.author || 'unknown'}</span>
                  <span className="comment-time">{(c.date || '').slice(0, 19)}</span>
                </div>
                <div className="comment-body">{c.text}</div>
              </div>
            ))}
          </div>
        )}

        {/* Composer */}
        <div className="comment-composer">
          <textarea
            value={commentDraft}
            onChange={(e) => setCommentDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                onPostComment();
              }
            }}
            disabled={commenting}
            placeholder="Add a comment…  (⌘+Enter to post)"
            rows={3}
            className="composer-textarea"
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
            <button
              onClick={onPostComment}
              disabled={commenting || !commentDraft.trim()}
              className="btn-primary btn-sm"
            >
              {commenting ? 'Posting…' : 'Post comment'}
            </button>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              Comments fire the TPM dispatch hook — bound TPM session will see this.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Status / Priority pills ────────────────────────────────────────────

function StatusPill({
  status,
  onChange,
  disabled,
}: {
  status: number;
  onChange: (v: number) => void;
  disabled: boolean;
}) {
  const opt = STATUS_OPTIONS.find((o) => o.value === status) || STATUS_OPTIONS[0];
  return (
    <div className="pill-group">
      <span className="pill-label">Status</span>
      <select
        value={status}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="pill-select"
        style={{ color: opt.color, fontWeight: 600 }}
      >
        {STATUS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function PriorityPill({
  priority,
  onChange,
  disabled,
}: {
  priority: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="pill-group">
      <span className="pill-label">Priority</span>
      <select
        value={priority}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="pill-select"
      >
        {PRIORITY_OPTIONS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
    </div>
  );
}

function Pill({ label, value, muted }: { label: string; value: React.ReactNode; muted?: boolean }) {
  return (
    <div className="pill-group">
      <span className="pill-label">{label}</span>
      <span className={`pill-value ${muted ? 'muted' : ''}`}>{value}</span>
    </div>
  );
}

// ── Dependency list ───────────────────────────────────────────────────

function DepList({
  label,
  items,
}: {
  label: string;
  items: { id: number; headline: string | null; status: number | null }[];
}) {
  return (
    <div>
      <div className="dep-list-label">{label}</div>
      {items.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>none</div>
      ) : (
        <ul className="dep-list">
          {items.map((d) => (
            <li key={d.id}>
              <Link to={`/tickets/${d.id}`} className="dep-link">
                <code>#{d.id}</code> {d.headline || '(no headline)'}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
