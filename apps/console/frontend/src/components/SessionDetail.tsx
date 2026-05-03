/**
 * SessionDetail — drill-in view for one session (Task #18 Part B).
 *
 * Shows:
 * - Header: session id, profile, ticket binding, status, cost, created_at
 * - Conversation transcript rendered from Adapter.render_history
 * - For active sessions: input box + Send button (POST /sessions/:id/messages)
 *
 * Reuses the MVTH spawn_session/append_message machinery — no streaming.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  appendMessage,
  closeSession,
  getSession,
  getSessionHistory,
} from '../api';
import { sseBus } from '../lib/sseBus';
import type { RenderedHistoryMessage, Session } from '../types';

interface PendingMessage {
  role: 'user' | 'assistant';
  text: string;
  ts: number;
  pending?: boolean;
}

export default function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const sessionId = id || '';
  const [session, setSession] = useState<Session | null>(null);
  const [history, setHistory] = useState<RenderedHistoryMessage[]>([]);
  const [pending, setPending] = useState<PendingMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const [s, h] = await Promise.all([
        getSession(sessionId),
        getSessionHistory(sessionId).catch((e) => {
          // History endpoint failure shouldn't blow away the metadata
          // pane. Surface the error inline but keep going.
          console.warn('history fetch failed:', e);
          return { messages: [] as RenderedHistoryMessage[], total: 0 };
        }),
      ]);
      setSession(s);
      setHistory(h.messages);
      // Once we've fetched server-side history, drop the optimistic
      // pending list — anything truly persisted is now in `history`.
      setPending([]);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
    // Polling kept as a backstop in case SSE is unavailable / lossy.
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  }, [refresh]);

  // Live updates via SSE: append new messages + bump cumulative cost as
  // they happen. Filtered to the current session_id so we don't render
  // events from sibling sessions.
  useEffect(() => {
    if (!sessionId) return;
    const offMsg = sseBus.subscribe('session.message_appended', (ev) => {
      const p = ev.payload as {
        session_id?: string;
        role?: 'user' | 'assistant';
        text?: string;
      };
      if (p.session_id !== sessionId) return;
      // Only react to assistant turns the server confirms — the user
      // turn was added optimistically in onSend below and would
      // otherwise show up twice. The user-role event is still useful
      // to clients that didn't trigger the message (e.g. another tab).
      if (p.role === 'assistant') {
        // Replace any pending placeholder, otherwise append.
        setPending((prev) => {
          const ph = prev.findIndex(
            (m) => m.role === 'assistant' && m.pending
          );
          const next: PendingMessage = {
            role: 'assistant',
            text: p.text || '',
            ts: Date.now(),
          };
          if (ph >= 0) {
            const copy = [...prev];
            copy[ph] = next;
            return copy;
          }
          return [...prev, next];
        });
      } else if (p.role === 'user') {
        // Only show if we don't already have an optimistic copy with
        // identical text in our pending buffer (avoid double-render in
        // the tab that sent the message). Use trimmed-equality for the
        // same reason.
        setPending((prev) => {
          const seen = prev.some(
            (m) => m.role === 'user' && m.text.trim() === (p.text || '').trim()
          );
          if (seen) return prev;
          return [
            ...prev,
            { role: 'user', text: p.text || '', ts: Date.now() },
          ];
        });
      }
    });
    const offCost = sseBus.subscribe('session.cost_updated', (ev) => {
      const p = ev.payload as {
        session_id?: string;
        cost_tokens_in?: number;
        cost_tokens_out?: number;
      };
      if (p.session_id !== sessionId) return;
      setSession((prev) =>
        prev
          ? {
              ...prev,
              cost_tokens_in: p.cost_tokens_in ?? prev.cost_tokens_in,
              cost_tokens_out: p.cost_tokens_out ?? prev.cost_tokens_out,
            }
          : prev
      );
    });
    const offClosed = sseBus.subscribe('session.closed', (ev) => {
      const p = ev.payload as { session_id?: string };
      if (p.session_id !== sessionId) return;
      setSession((prev) => (prev ? { ...prev, status: 'closed' } : prev));
    });
    return () => {
      offMsg();
      offCost();
      offClosed();
    };
  }, [sessionId]);

  async function onSend() {
    const text = draft.trim();
    if (!text || !session || busy) return;
    setBusy(true);
    setError(null);
    const ts = Date.now();
    setPending((p) => [
      ...p,
      { role: 'user', text, ts },
      { role: 'assistant', text: '… thinking …', ts: ts + 1, pending: true },
    ]);
    setDraft('');
    try {
      const result = await appendMessage(session.id, text);
      // Replace the placeholder assistant turn with the real reply.
      setPending((p) =>
        p.map((m) =>
          m.ts === ts + 1
            ? { role: 'assistant', text: result.assistant_text, ts: m.ts }
            : m
        )
      );
      // Refresh server state next tick so cost / native_handle are fresh.
      setTimeout(refresh, 250);
    } catch (e) {
      setError(String(e));
      setPending((p) =>
        p.map((m) =>
          m.ts === ts + 1
            ? { role: 'assistant', text: `Error: ${String(e)}`, ts: m.ts }
            : m
        )
      );
    } finally {
      setBusy(false);
    }
  }

  async function onClose() {
    if (!session || busy) return;
    setBusy(true);
    try {
      await closeSession(session.id);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="loading">Loading session…</p>;
  if (!session)
    return (
      <div>
        <div className="error">Session not found.</div>
        <p>
          <Link to="/sessions">← back to Sessions</Link>
        </p>
      </div>
    );

  const allMessages = [
    ...history.map<PendingMessage>((m) => ({
      role: m.role,
      text: m.text,
      ts: Date.parse(m.timestamp || '') || 0,
    })),
    ...pending,
  ];

  return (
    <div>
      <div className="page-header">
        <h2>
          Session <code style={{ fontSize: 14 }}>{session.id}</code>
        </h2>
        <span className="subtitle">
          <Link to="/sessions">← all sessions</Link>
        </span>
      </div>

      {/* Metadata */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div className="grid grid-3">
          <Meta label="Profile" value={session.profile_name} />
          <Meta label="Status" value={<StatusBadge status={session.status} />} />
          <Meta
            label="Binding"
            value={
              <>
                {session.binding_kind}
                {session.ticket_id && ` · ticket #${session.ticket_id}`}
                {session.channel_id && ` · ${session.channel_id}`}
              </>
            }
          />
          <Meta
            label="Tokens (in / out)"
            value={
              <>
                {(session.cost_tokens_in || 0).toLocaleString()} /{' '}
                {(session.cost_tokens_out || 0).toLocaleString()}
              </>
            }
          />
          <Meta label="Runner" value={session.runner_type} />
          <Meta label="Created" value={(session.created_at || '').slice(0, 19)} />
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}

      {/* Conversation */}
      <div className="card">
        <h3 style={{ marginTop: 0, display: 'flex', alignItems: 'center' }}>
          Conversation
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
            {history.length} server-persisted turn(s)
          </span>
        </h3>
        {allMessages.length === 0 ? (
          <div className="empty-state">No turns yet. Send a message below.</div>
        ) : (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              maxHeight: 540,
              overflowY: 'auto',
              marginBottom: 12,
            }}
          >
            {allMessages.map((m, i) => (
              <div
                key={`${m.ts}-${i}`}
                style={{
                  background:
                    m.role === 'user'
                      ? 'var(--bg-panel-hover)'
                      : 'var(--bg-panel)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: 8,
                  opacity: m.pending ? 0.7 : 1,
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    marginBottom: 4,
                  }}
                >
                  {m.role}
                </div>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.text}</div>
              </div>
            ))}
          </div>
        )}

        {/* Input */}
        {session.status === 'active' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={busy}
              placeholder="Send a message to this session…"
              rows={3}
              style={{
                width: '100%',
                padding: 8,
                background: 'var(--bg)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                fontFamily: 'inherit',
                fontSize: 13,
                resize: 'vertical',
              }}
            />
            <div>
              <button onClick={onSend} disabled={busy || !draft.trim()}>
                {busy ? 'Sending…' : 'Send'}
              </button>
              <button
                onClick={onClose}
                disabled={busy}
                style={{ marginLeft: 8 }}
              >
                Close session
              </button>
            </div>
          </div>
        ) : (
          <div className="empty-state">Session is closed; cannot send more messages.</div>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ fontSize: 13 }}>{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? '#4ade80' : 'var(--text-muted)';
  return (
    <span style={{ color, fontWeight: 600, fontSize: 13 }}>{status}</span>
  );
}
