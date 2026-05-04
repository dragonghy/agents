/**
 * SessionDetail — drill-in view for one session.
 *
 * Renders the full conversation history including tool calls (collapsible
 * panels for input + result), streaming indicator while the assistant is
 * mid-turn, per-message timestamps, and an inline composer for active
 * sessions. SSE events keep cost/messages/status live without polling.
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
import type {
  RenderedHistoryMessage,
  RenderedToolCall,
  Session,
} from '../types';

/** A pending optimistic / streaming entry not yet on the server transcript. */
interface PendingMessage {
  role: 'user' | 'assistant';
  text: string;
  ts: number;
  pending?: boolean;
  /** Streaming chunks accumulate here as SSE events arrive. */
  streaming?: boolean;
}

const STREAMING_FRESH_MS = 4000; // how recent counts as "agent is replying now"

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
  // Track when we last saw a server-side assistant chunk arrive — used to
  // render the "live" streaming dot at the top of the page.
  const [lastChunkAt, setLastChunkAt] = useState<number>(0);
  const [, forceTick] = useState(0);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const [s, h] = await Promise.all([
        getSession(sessionId),
        getSessionHistory(sessionId).catch((e) => {
          console.warn('history fetch failed:', e);
          return { messages: [] as RenderedHistoryMessage[], total: 0 };
        }),
      ]);
      setSession(s);
      setHistory(h.messages);
      // Drop any optimistic pending entries that the server has now
      // confirmed; anything that survived a refresh isn't on disk yet.
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

  // Re-render every second while a stream is fresh so the "live N…s ago"
  // indicator updates without us recomputing on every event.
  useEffect(() => {
    if (!lastChunkAt) return;
    const t = setInterval(() => forceTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, [lastChunkAt]);

  // Live SSE: append messages, bump cost, mark closed, drive streaming
  // indicator — all filtered to this session id.
  useEffect(() => {
    if (!sessionId) return;
    const offMsg = sseBus.subscribe('session.message_appended', (ev) => {
      const p = ev.payload as {
        session_id?: string;
        role?: 'user' | 'assistant';
        text?: string;
      };
      if (p.session_id !== sessionId) return;
      if (p.role === 'assistant') {
        setLastChunkAt(Date.now());
        // Each assistant chunk lands as a fresh pending entry. The
        // backend now publishes once per AssistantMessage instead of
        // one big aggregate per turn (commit 636d0e6) — show each one.
        setPending((prev) => {
          // Merge: if there's a pending placeholder ("… thinking …"),
          // replace it with the first real chunk; otherwise append.
          const placeholderIdx = prev.findIndex(
            (m) => m.role === 'assistant' && m.pending
          );
          const next: PendingMessage = {
            role: 'assistant',
            text: p.text || '',
            ts: Date.now(),
          };
          if (placeholderIdx >= 0) {
            const copy = [...prev];
            copy[placeholderIdx] = next;
            return copy;
          }
          return [...prev, next];
        });
      } else if (p.role === 'user') {
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
      { role: 'assistant', text: '', ts: ts + 1, pending: true },
    ]);
    setDraft('');
    try {
      // The append call returns when the SDK turn finishes; with streaming
      // wired up, intermediate chunks arrive via SSE before this resolves.
      await appendMessage(session.id, text);
      // Refresh server state so cost / native_handle catch up.
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

  // Merge server-persisted history with optimistic pending — pending
  // entries are tagged so we can render them slightly transparent.
  const allMessages: Array<
    | { kind: 'history'; m: RenderedHistoryMessage; key: string }
    | { kind: 'pending'; m: PendingMessage; key: string }
  > = [
    ...history.map((m, i) => ({
      kind: 'history' as const,
      m,
      key: `h-${i}-${m.timestamp}`,
    })),
    ...pending.map((m) => ({
      kind: 'pending' as const,
      m,
      key: `p-${m.ts}`,
    })),
  ];

  const isStreaming =
    session.status === 'active' &&
    lastChunkAt > 0 &&
    Date.now() - lastChunkAt < STREAMING_FRESH_MS;

  return (
    <div>
      <div className="page-header">
        <h2>
          Session <code style={{ fontSize: 14 }}>{session.id}</code>
          {isStreaming && <StreamingDot />}
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
                {session.ticket_id && (
                  <>
                    {' · '}
                    <Link to={`/tickets/${session.ticket_id}`}>
                      ticket #{session.ticket_id}
                    </Link>
                  </>
                )}
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
            {isStreaming && (
              <span style={{ color: 'var(--status-active)', marginLeft: 8 }}>
                · streaming…
              </span>
            )}
          </span>
        </h3>
        {allMessages.length === 0 ? (
          <div className="empty-state">No turns yet. Send a message below.</div>
        ) : (
          <div className="conversation-scroll">
            {allMessages.map((entry) => {
              if (entry.kind === 'pending') {
                return (
                  <PendingBubble key={entry.key} m={entry.m} />
                );
              }
              return <HistoryBubble key={entry.key} m={entry.m} />;
            })}
          </div>
        )}

        {/* Input */}
        {session.status === 'active' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Cmd/Ctrl+Enter sends; plain Enter inserts newline.
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                  e.preventDefault();
                  onSend();
                }
              }}
              disabled={busy}
              placeholder="Send a message to this session…  (⌘+Enter to send)"
              rows={3}
              className="composer-textarea"
            />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button onClick={onSend} disabled={busy || !draft.trim()} className="btn-primary">
                {busy ? 'Sending…' : 'Send'}
              </button>
              <button onClick={onClose} disabled={busy} className="btn-secondary">
                Close session
              </button>
              {busy && (
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  agent working…
                </span>
              )}
            </div>
          </div>
        ) : (
          <div className="empty-state" style={{ marginTop: 12 }}>
            Session is closed; cannot send more messages.
          </div>
        )}
      </div>
    </div>
  );
}

// ── Bubbles ────────────────────────────────────────────────────────────

function HistoryBubble({ m }: { m: RenderedHistoryMessage }) {
  return <Bubble role={m.role} text={m.text} timestamp={m.timestamp} toolCalls={m.tool_calls} />;
}

function PendingBubble({ m }: { m: PendingMessage }) {
  return (
    <Bubble
      role={m.role}
      text={m.text || (m.pending ? '…' : '')}
      timestamp={new Date(m.ts).toISOString()}
      pending={m.pending}
    />
  );
}

function Bubble({
  role,
  text,
  timestamp,
  toolCalls,
  pending,
}: {
  role: 'user' | 'assistant';
  text: string;
  timestamp?: string;
  toolCalls?: RenderedToolCall[];
  pending?: boolean;
}) {
  const time = timestamp ? formatTime(timestamp) : '';
  return (
    <div className={`bubble bubble-${role}`} style={{ opacity: pending ? 0.65 : 1 }}>
      <div className="bubble-meta">
        <span className="bubble-role">{role}</span>
        {time && <span className="bubble-time">{time}</span>}
      </div>
      {text && <div className="bubble-text">{text}</div>}
      {toolCalls && toolCalls.length > 0 && (
        <div className="tool-calls-list">
          {toolCalls.map((tc) => (
            <ToolCallPanel key={tc.id} tc={tc} />
          ))}
        </div>
      )}
      {!text && (!toolCalls || toolCalls.length === 0) && pending && (
        <div className="bubble-text" style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
          thinking…
        </div>
      )}
    </div>
  );
}

// ── Tool call panel ───────────────────────────────────────────────────

function ToolCallPanel({ tc }: { tc: RenderedToolCall }) {
  const [open, setOpen] = useState(false);
  const summary = summarizeToolInput(tc);
  const hasResult = tc.result !== null && tc.result !== undefined;
  const errored = tc.is_error === true;

  return (
    <div
      className={`tool-panel ${open ? 'tool-panel-open' : ''} ${errored ? 'tool-panel-error' : ''}`}
    >
      <button
        className="tool-panel-header"
        onClick={() => setOpen((o) => !o)}
        type="button"
        title={open ? 'collapse' : 'expand'}
      >
        <span className="tool-chevron">{open ? '▼' : '▶'}</span>
        <span className="tool-name">{tc.name}</span>
        {summary && <span className="tool-summary">{summary}</span>}
        <span className="tool-status">
          {errored ? '✗ error' : hasResult ? '✓' : '…'}
        </span>
      </button>
      {open && (
        <div className="tool-panel-body">
          <ToolBlock label="Input">
            <pre className="tool-pre">{prettyJSON(tc.input)}</pre>
          </ToolBlock>
          {hasResult && (
            <ToolBlock label={errored ? 'Error' : 'Result'}>
              <pre className="tool-pre">{stringifyResult(tc.result)}</pre>
            </ToolBlock>
          )}
          {!hasResult && (
            <div className="tool-pending">No result yet — tool may still be running.</div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="tool-block">
      <div className="tool-block-label">{label}</div>
      {children}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────

function summarizeToolInput(tc: RenderedToolCall): string {
  // Quick one-liner extracted from common tool inputs so users don't have
  // to expand every panel just to see what was called.
  const name = tc.name.toLowerCase();
  const i = tc.input || {};
  if (name === 'bash' && typeof i.command === 'string') {
    return truncate(i.command, 80);
  }
  if ((name === 'read' || name === 'edit' || name === 'write') && typeof i.file_path === 'string') {
    return truncate(i.file_path, 80);
  }
  if (name === 'grep' && typeof i.pattern === 'string') {
    return `${i.pattern}${i.path ? ` in ${i.path}` : ''}`;
  }
  if (name === 'glob' && typeof i.pattern === 'string') {
    return String(i.pattern);
  }
  if (name === 'webfetch' && typeof i.url === 'string') {
    return truncate(i.url, 80);
  }
  // For MCP tools we get names like "mcp__agents__add_comment" — strip
  // the prefix so the chip stays readable.
  // Fall back to first string-valued arg, truncated.
  for (const v of Object.values(i)) {
    if (typeof v === 'string') return truncate(v, 80);
  }
  return '';
}

function prettyJSON(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function stringifyResult(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  // Some SDKs return result as a list of {type, text} blocks. Concatenate text.
  if (Array.isArray(v)) {
    const parts = v.map((b) => {
      if (b && typeof b === 'object' && 'text' in b && typeof (b as { text: unknown }).text === 'string') {
        return (b as { text: string }).text;
      }
      return prettyJSON(b);
    });
    return parts.join('\n');
  }
  return prettyJSON(v);
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + '…';
}

function formatTime(iso: string): string {
  // ISO 8601 → "HH:MM:SS"
  const m = /T(\d\d):(\d\d):(\d\d)/.exec(iso);
  if (m) return `${m[1]}:${m[2]}:${m[3]}`;
  return iso.slice(0, 19);
}

// ── Tiny components ────────────────────────────────────────────────────

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 13 }}>{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? 'var(--status-active)' : 'var(--text-muted)';
  return (
    <span style={{ color, fontWeight: 600, fontSize: 13 }}>{status}</span>
  );
}

function StreamingDot() {
  return (
    <span
      title="receiving live output"
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: 'var(--status-active)',
        marginLeft: 10,
        verticalAlign: 'middle',
        boxShadow: '0 0 6px var(--status-active)',
        animation: 'streamingPulse 1.2s ease-in-out infinite',
      }}
    />
  );
}
