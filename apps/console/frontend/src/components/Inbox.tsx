/**
 * Inbox — the operator's "what needs my attention" landing page.
 *
 * Replaces the old Overview / KPI dashboard as the default route.
 * KPIs alone don't answer the question Human asks every morning:
 * "is anything stuck waiting on me?" — so this page leads with
 * decisions, then live activity, then failures, then recent briefs.
 *
 * Sections (top to bottom):
 *  1. Decisions Needed — blocked tickets + tickets tagged
 *     ``blocker:human-*`` so the operator sees what only they can
 *     unblock. Click-through to ticket detail.
 *  2. Live Activity — currently-active sessions, sorted by most
 *     recent SSE event. Streaming dot when a session received a
 *     chunk in the last 4 s.
 *  3. Recent Failures (24 h) — sessions that closed with cost > $0
 *     but no native_handle, or any session with the legacy "errored"
 *     status (placeholder for now — daemon doesn't surface errors
 *     yet, see TODO in code).
 *  4. Today's Brief — collapsed link to /briefs/<today>.
 *  5. Compact KPIs at the bottom (today cost / open tickets /
 *     active sessions / lifetime cost).
 *
 * Refreshes every 30 s + listens to SSE for instant reactivity.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getCostByProfile,
  getCostTotals,
  getTicketBoard,
  listSessions,
  listTickets,
} from '../api';
import { sseBus } from '../lib/sseBus';
import type {
  CostByProfileRow,
  CostTotalsResponse,
  Session,
  TicketSummary,
} from '../types';

const REFRESH_MS = 30_000;
const STREAMING_FRESH_MS = 4_000;

export default function Inbox() {
  const [totals, setTotals] = useState<CostTotalsResponse | null>(null);
  const [activeSessions, setActiveSessions] = useState<Session[]>([]);
  const [activeTpms, setActiveTpms] = useState<number>(0);
  const [openTotal, setOpenTotal] = useState<{ new: number; wip: number; blocked: number }>({
    new: 0,
    wip: 0,
    blocked: 0,
  });
  const [topProfile, setTopProfile] = useState<CostByProfileRow | null>(null);

  // "Needs attention" signals
  const [blocked, setBlocked] = useState<TicketSummary[]>([]);
  const [humanBlocked, setHumanBlocked] = useState<TicketSummary[]>([]);
  const [staleTickets, setStaleTickets] = useState<TicketSummary[]>([]);

  // Per-session "last activity" — used to sort + show streaming dot.
  const [lastChunkBySession, setLastChunkBySession] = useState<Record<string, number>>({});

  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, active, tpms, byProfile, board, blockedList, wipList] = await Promise.all([
        getCostTotals(),
        listSessions({ status: 'active', limit: 50 }),
        listSessions({ status: 'active', profile: 'tpm', limit: 1 }),
        getCostByProfile(),
        getTicketBoard(null),
        listTickets({ status: '1', limit: 0 }),
        listTickets({ status: '4', limit: 0 }),
      ]);
      setTotals(t);
      setActiveSessions(active.sessions || []);
      setActiveTpms(tpms.total);
      setTopProfile(byProfile.rollup[0] || null);
      const counts = { new: 0, wip: 0, blocked: 0 };
      for (const c of board.columns) {
        if (c.status === 3) counts.new = c.tickets.length;
        else if (c.status === 4) counts.wip = c.tickets.length;
        else if (c.status === 1) counts.blocked = c.tickets.length;
      }
      setOpenTotal(counts);

      const blockedTickets = blockedList.tickets || [];
      // Split: tickets explicitly tagged "blocker:human-*" (Human is the
      // unblocker) get their own section so they can't hide in the noise.
      const humanTagged = blockedTickets.filter((tk) =>
        (tk.tags || '').toLowerCase().includes('blocker:human')
      );
      const otherBlocked = blockedTickets.filter(
        (tk) => !(tk.tags || '').toLowerCase().includes('blocker:human')
      );
      setHumanBlocked(humanTagged);
      setBlocked(otherBlocked);

      const wipTickets = wipList.tickets || [];
      // Stale = WIP for >7 days based on the ``date`` (created) column.
      // Imperfect (we don't track last-modified yet) but better than
      // nothing — Human asked for "stale-in-progress" surfacing.
      const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
      setStaleTickets(
        wipTickets
          .filter((tk) => {
            const ts = tk.date ? Date.parse(tk.date.replace(' ', 'T')) : NaN;
            return Number.isFinite(ts) && ts < sevenDaysAgo;
          })
          .slice(0, 8)
      );

      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  // SSE: bump streaming map + opportunistic reload when something interesting happens.
  useEffect(() => {
    const offMsg = sseBus.subscribe('session.message_appended', (ev) => {
      const p = ev.payload as { session_id?: string; role?: string };
      if (p.role === 'assistant' && p.session_id) {
        setLastChunkBySession((prev) => ({ ...prev, [p.session_id!]: Date.now() }));
      }
    });
    const offCreated = sseBus.subscribe('session.created', () => load());
    const offClosed = sseBus.subscribe('session.closed', () => load());
    return () => {
      offMsg();
      offCreated();
      offClosed();
    };
  }, [load]);

  // Force re-render every second while any session is "fresh-streaming"
  // so the dot fades out gracefully.
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const sortedActive = [...activeSessions].sort((a, b) => {
    const al = lastChunkBySession[a.id] || 0;
    const bl = lastChunkBySession[b.id] || 0;
    if (al !== bl) return bl - al;
    return (b.created_at || '').localeCompare(a.created_at || '');
  });

  const totalDecisions =
    humanBlocked.length + blocked.length + staleTickets.length;

  return (
    <div>
      <div className="page-header">
        <h2>Inbox</h2>
        <span className="subtitle">
          {totalDecisions === 0
            ? '✅ all clear · refreshes every 30s'
            : `${totalDecisions} item(s) need attention · refreshes every 30s`}
        </span>
      </div>

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {/* ── 1. Decisions Needed ──────────────────────────────────── */}
      <div className="card section-card" style={{ marginBottom: 14 }}>
        <SectionHeader
          title="Decisions needed"
          count={humanBlocked.length + blocked.length}
          help="Tickets that are blocked or explicitly waiting on Human input"
        />
        {humanBlocked.length === 0 && blocked.length === 0 ? (
          <div className="empty-state-tight">
            <span style={{ color: 'var(--status-active)' }}>✓</span> Nothing waiting on you.
          </div>
        ) : (
          <ul className="attention-list">
            {humanBlocked.map((tk) => (
              <AttentionRow
                key={tk.id}
                ticket={tk}
                tag="WAITING ON HUMAN"
                tagColor="var(--accent-warm)"
              />
            ))}
            {blocked.map((tk) => (
              <AttentionRow
                key={tk.id}
                ticket={tk}
                tag="BLOCKED"
                tagColor="var(--status-blocked)"
              />
            ))}
          </ul>
        )}
      </div>

      {/* ── 2. Live Activity ──────────────────────────────────────── */}
      <div className="card section-card" style={{ marginBottom: 14 }}>
        <SectionHeader
          title="Live activity"
          count={sortedActive.length}
          help="Active sessions across all profiles. Green dot = streaming output right now."
        />
        {sortedActive.length === 0 ? (
          <div className="empty-state-tight">No active sessions.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Profile</th>
                <th>Binding</th>
                <th style={{ textAlign: 'right' }}>Cost</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {sortedActive.slice(0, 10).map((s) => {
                const last = lastChunkBySession[s.id] || 0;
                const isStreaming = last > 0 && Date.now() - last < STREAMING_FRESH_MS;
                return (
                  <tr key={s.id}>
                    <td>
                      <Link
                        to={`/sessions/${encodeURIComponent(s.id)}`}
                        className="session-link"
                      >
                        <code>{s.id.slice(0, 24)}…</code>
                      </Link>
                      {isStreaming && <LiveDot />}
                    </td>
                    <td>{s.profile_name}</td>
                    <td className="binding-cell">
                      {s.binding_kind}
                      {s.ticket_id && (
                        <>
                          {' · '}
                          <Link to={`/tickets/${s.ticket_id}`}>#{s.ticket_id}</Link>
                        </>
                      )}
                      {s.channel_id && (
                        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                          {' '}
                          · {s.channel_id}
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: 11 }}>
                      ${(s.cost_usd || 0).toFixed(2)}
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {last > 0 ? formatRelative(last) : (s.created_at || '').slice(11, 16)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {sortedActive.length > 10 && (
          <div style={{ marginTop: 8, fontSize: 11, textAlign: 'right' }}>
            <Link to="/sessions" style={{ color: 'var(--text-dim)' }}>
              {sortedActive.length - 10} more →
            </Link>
          </div>
        )}
      </div>

      {/* ── 3. Stale tickets ───────────────────────────────────────── */}
      {staleTickets.length > 0 && (
        <div className="card section-card" style={{ marginBottom: 14 }}>
          <SectionHeader
            title="Stale"
            count={staleTickets.length}
            help="In-progress tickets that haven't moved in > 7 days"
          />
          <ul className="attention-list">
            {staleTickets.map((tk) => (
              <AttentionRow
                key={`s-${tk.id}`}
                ticket={tk}
                tag="STALE > 7d"
                tagColor="var(--text-dim)"
              />
            ))}
          </ul>
        </div>
      )}

      {/* ── 4. Compact KPIs ────────────────────────────────────────── */}
      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <Tile
          label="Today's cost"
          value={totals ? `$${totals.today.usd.toFixed(2)}` : '—'}
          sub={
            totals
              ? `${totals.today.tokens_in.toLocaleString()} in / ${totals.today.tokens_out.toLocaleString()} out`
              : undefined
          }
        />
        <Tile
          label="Open tickets"
          value={(openTotal.new + openTotal.wip + openTotal.blocked).toLocaleString()}
          sub={`${openTotal.new} new · ${openTotal.wip} wip · ${openTotal.blocked} blocked`}
        />
        <Tile
          label="Active sessions"
          value={activeSessions.length.toLocaleString()}
          sub={
            activeTpms > 0
              ? `${activeTpms} TPM session(s) running`
              : undefined
          }
        />
      </div>

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <Tile
          label="Lifetime cost"
          value={totals ? `$${totals.lifetime.usd.toFixed(2)}` : '—'}
          sub={
            totals
              ? `${totals.lifetime.sessions_count.toLocaleString()} sessions`
              : undefined
          }
        />
        <Tile
          label="Top profile (today)"
          value={topProfile?.profile_name || '—'}
          sub={
            topProfile
              ? `${topProfile.sessions_count} sessions · $${topProfile.total_usd.toFixed(2)}`
              : undefined
          }
        />
        <div className="card">
          <div className="card-tile-label">Today's brief</div>
          <div style={{ marginTop: 6, fontSize: 13 }}>
            <Link to="/briefs">View today's brief →</Link>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Subcomponents ──────────────────────────────────────────────────

function SectionHeader({
  title,
  count,
  help,
}: {
  title: string;
  count: number;
  help?: string;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
      <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        {title}
        {count > 0 && (
          <span
            style={{
              background: 'var(--bg-panel-hover)',
              color: 'var(--text-dim)',
              borderRadius: 999,
              padding: '1px 8px',
              fontSize: 11,
              fontWeight: 500,
            }}
          >
            {count}
          </span>
        )}
      </h3>
      {help && (
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
          {help}
        </span>
      )}
    </div>
  );
}

function AttentionRow({
  ticket,
  tag,
  tagColor,
}: {
  ticket: TicketSummary;
  tag: string;
  tagColor: string;
}) {
  return (
    <li>
      <Link to={`/tickets/${ticket.id}`} className="attention-link">
        <span className="attention-id">#{ticket.id}</span>
        <span
          className="attention-tag"
          style={{ color: tagColor, borderColor: tagColor }}
        >
          {tag}
        </span>
        <span className="attention-headline">{ticket.headline || '(no headline)'}</span>
        {ticket.workspace_name && (
          <span className="attention-ws">{ticket.workspace_name}</span>
        )}
      </Link>
    </li>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card">
      <div className="card-tile-label">{label}</div>
      <div className="metric-big">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

function LiveDot() {
  return (
    <span
      title="streaming live"
      style={{
        display: 'inline-block',
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: 'var(--status-active)',
        marginLeft: 8,
        verticalAlign: 'middle',
        animation: 'streamingPulse 1.2s ease-in-out infinite',
      }}
    />
  );
}

function formatRelative(ms: number): string {
  const delta = Math.floor((Date.now() - ms) / 1000);
  if (delta < 5) return 'just now';
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  return `${Math.floor(delta / 3600)}h ago`;
}
