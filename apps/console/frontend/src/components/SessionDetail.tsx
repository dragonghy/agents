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
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  }, [refresh]);

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
