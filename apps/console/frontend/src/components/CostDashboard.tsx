/**
 * CostDashboard — orchestration v1 cost view (Task #18 Part A).
 *
 * Three-tab pivot over session-derived data:
 *   1. By Session — paginated table of recent sessions with token + USD.
 *   2. By Profile — rollup grouped by profile_name.
 *   3. By Ticket  — rollup grouped by ticket_id.
 *
 * Plus today / 7-day / lifetime totals at the top, sourced from
 * ``session.created_at`` + cost_tokens_in/out (NOT the legacy
 * token_usage_daily table).
 *
 * Per Finding #3 (ui-findings-2026-05-03.md): the by-Agent pivot is gone
 * because Agent isn't a thing anymore — Profile and Session are the new
 * dimensions and they are independent.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  getCostByDay,
  getCostBySession,
  getCostByProfile,
  getCostByTicket,
  getCostTotals,
} from '../api';
import type { CostByDayRow } from '../api';
import { sseBus } from '../lib/sseBus';
import type {
  CostBySessionRow,
  CostByProfileRow,
  CostByTicketRow,
  CostTotalsResponse,
} from '../types';

const REFRESH_MS = 30000;
type Tab = 'session' | 'profile' | 'ticket';

function fmtUsd(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtNum(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString('en-US');
}

function shortDate(s: string | null | undefined): string {
  if (!s) return '—';
  // SQLite gives us "YYYY-MM-DD HH:MM:SS"; show first 16 chars.
  return s.slice(0, 16);
}

export default function CostDashboard() {
  const [totals, setTotals] = useState<CostTotalsResponse | null>(null);
  const [sessionRows, setSessionRows] = useState<CostBySessionRow[]>([]);
  const [sessionTotal, setSessionTotal] = useState<number>(0);
  const [profileRows, setProfileRows] = useState<CostByProfileRow[]>([]);
  const [ticketRows, setTicketRows] = useState<CostByTicketRow[]>([]);
  const [byDay, setByDay] = useState<CostByDayRow[]>([]);
  const [trendDays, setTrendDays] = useState<number>(30);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('session');
  const [offset, setOffset] = useState<number>(0);
  const limit = 50;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [t, byS, byP, byT, byD] = await Promise.all([
          getCostTotals(),
          getCostBySession({ limit, offset }),
          getCostByProfile(),
          getCostByTicket(),
          getCostByDay(trendDays),
        ]);
        if (cancelled) return;
        setTotals(t);
        setSessionRows(byS.sessions);
        setSessionTotal(byS.total);
        setProfileRows(byP.rollup);
        setTicketRows(byT.rollup);
        setByDay(fillTrendGaps(byD.days, trendDays));
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(String(e));
      }
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    // Live totals tile: refresh on every cost_updated. Other tabs
    // (by-session / by-profile / by-ticket pivots) keep polling — those
    // include rollups + USD math that's cheaper to compute server-side
    // than to reproduce in the listener.
    const offCost = sseBus.subscribe('session.cost_updated', async () => {
      try {
        const t = await getCostTotals();
        if (!cancelled) setTotals(t);
      } catch {
        // ignore — polling will catch up
      }
    });
    return () => {
      cancelled = true;
      clearInterval(id);
      offCost();
    };
  }, [offset, trendDays]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(sessionTotal / limit)),
    [sessionTotal]
  );
  const currentPage = Math.floor(offset / limit) + 1;

  if (error) return <div className="error">{error}</div>;
  if (!totals) return <p className="loading">Loading cost dashboard…</p>;

  return (
    <div>
      <div className="page-header">
        <h2>Cost</h2>
        <span className="subtitle">
          sourced from session.cost_tokens_in/out · refreshes every 30s
        </span>
      </div>

      {/* ── Top-of-page totals ── */}
      <div className="grid grid-3">
        <div className="card">
          <h3>Today</h3>
          <div className="metric-big">${fmtUsd(totals.today.usd)}</div>
          <div className="metric-sub">
            {fmtNum(totals.today.tokens_in)} in / {fmtNum(totals.today.tokens_out)} out
            · {fmtNum(totals.today.sessions_count)} sess
          </div>
        </div>
        <div className="card">
          <h3>Last 7 days</h3>
          <div className="metric-big">${fmtUsd(totals.week.usd)}</div>
          <div className="metric-sub">
            {fmtNum(totals.week.tokens_in)} in / {fmtNum(totals.week.tokens_out)} out
            · {fmtNum(totals.week.sessions_count)} sess
          </div>
        </div>
        <div className="card">
          <h3>Lifetime</h3>
          <div className="metric-big">${fmtUsd(totals.lifetime.usd)}</div>
          <div className="metric-sub">
            {fmtNum(totals.lifetime.tokens_in)} in / {fmtNum(totals.lifetime.tokens_out)} out
            · {fmtNum(totals.lifetime.sessions_count)} sess
          </div>
        </div>
      </div>

      {/* ── Trend chart ── */}
      <div className="card" style={{ marginTop: 16, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Daily cost · last {trendDays} days</h3>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            {[7, 14, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setTrendDays(d)}
                className={`filter-chip ${trendDays === d ? 'filter-chip-active' : ''}`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
        {byDay.length === 0 ? (
          <div className="empty-state">No cost data in the selected window.</div>
        ) : (
          <div style={{ width: '100%', height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={byDay} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="usdGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#60a5fa" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#60a5fa" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#232b3d" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(s) => (s as string).slice(5)} // MM-DD
                  stroke="#64748b"
                  fontSize={11}
                  interval="preserveStartEnd"
                />
                <YAxis
                  stroke="#64748b"
                  fontSize={11}
                  tickFormatter={(v) => `$${(v as number).toFixed(2)}`}
                  width={56}
                />
                <Tooltip
                  contentStyle={{
                    background: '#131826',
                    border: '1px solid #232b3d',
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: '#e2e8f0' }}
                  formatter={(v: number, name: string) =>
                    name === 'usd'
                      ? [`$${v.toFixed(2)}`, 'USD']
                      : name === 'sessions_count'
                      ? [v.toLocaleString(), 'sessions']
                      : [v.toLocaleString(), name]
                  }
                />
                <Area
                  type="monotone"
                  dataKey="usd"
                  stroke="#60a5fa"
                  strokeWidth={2}
                  fill="url(#usdGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
        <div style={{ marginTop: 8, display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-muted)' }}>
          <span>
            window total ${' '}
            <strong style={{ color: 'var(--text)' }}>
              {fmtUsd(byDay.reduce((acc, d) => acc + d.usd, 0))}
            </strong>
          </span>
          <span>
            avg/day ${' '}
            <strong style={{ color: 'var(--text)' }}>
              {fmtUsd(
                byDay.length === 0
                  ? 0
                  : byDay.reduce((acc, d) => acc + d.usd, 0) / byDay.length,
              )}
            </strong>
          </span>
          <span>
            peak ${' '}
            <strong style={{ color: 'var(--text)' }}>
              {fmtUsd(byDay.reduce((acc, d) => Math.max(acc, d.usd), 0))}
            </strong>
          </span>
        </div>
      </div>

      {/* ── Tabs ── */}
      <div
        style={{
          marginTop: 24,
          marginBottom: 8,
          display: 'flex',
          gap: 4,
          borderBottom: '1px solid var(--border)',
        }}
      >
        <TabBtn current={tab} value="session" label="By Session" set={setTab} />
        <TabBtn current={tab} value="profile" label="By Profile" set={setTab} />
        <TabBtn current={tab} value="ticket" label="By Ticket" set={setTab} />
      </div>

      {tab === 'session' && (
        <SessionTable
          rows={sessionRows}
          total={sessionTotal}
          currentPage={currentPage}
          totalPages={totalPages}
          onPrev={() => setOffset(Math.max(0, offset - limit))}
          onNext={() =>
            setOffset(
              Math.min(Math.max(0, sessionTotal - limit), offset + limit)
            )
          }
        />
      )}
      {tab === 'profile' && <ProfileTable rows={profileRows} />}
      {tab === 'ticket' && <TicketTable rows={ticketRows} />}

      <div className="refresh-note" style={{ marginTop: 12 }}>
        {totals.pricing.note} Input ${totals.pricing.input_per_million}/M,
        Output ${totals.pricing.output_per_million}/M.
      </div>
    </div>
  );
}

function TabBtn(props: {
  current: Tab;
  value: Tab;
  label: string;
  set: (t: Tab) => void;
}) {
  const active = props.current === props.value;
  return (
    <button
      onClick={() => props.set(props.value)}
      style={{
        padding: '8px 16px',
        background: active ? 'var(--bg-panel-hover)' : 'transparent',
        color: active ? 'var(--text)' : 'var(--text-dim)',
        border: 'none',
        borderBottom: active
          ? '2px solid var(--accent, #4f8cff)'
          : '2px solid transparent',
        cursor: 'pointer',
        fontFamily: 'inherit',
        fontSize: 13,
      }}
    >
      {props.label}
    </button>
  );
}

function SessionTable(props: {
  rows: CostBySessionRow[];
  total: number;
  currentPage: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  if (props.rows.length === 0) {
    return (
      <div className="card">
        <div className="empty-state">No sessions recorded yet.</div>
      </div>
    );
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>
        Sessions · {props.total} total · page {props.currentPage} / {props.totalPages}
      </h3>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Session</th>
            <th style={thStyle}>Profile</th>
            <th style={thStyle}>Ticket</th>
            <th style={thStyle}>Status</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Tokens in</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Tokens out</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>USD</th>
            <th style={thStyle}>Created</th>
          </tr>
        </thead>
        <tbody>
          {props.rows.map((s) => (
            <tr key={s.id}>
              <td style={tdStyle}>
                <code style={{ fontSize: 11 }}>{s.id}</code>
              </td>
              <td style={tdStyle}>{s.profile_name}</td>
              <td style={tdStyle}>
                {s.ticket_id ? `#${s.ticket_id}` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
              </td>
              <td style={tdStyle}>{s.status}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(s.cost_tokens_in)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(s.cost_tokens_out)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>${fmtUsd(s.cost_usd)}</td>
              <td style={tdStyle}>{shortDate(s.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <button onClick={props.onPrev} disabled={props.currentPage <= 1}>
          ← Prev
        </button>
        <button onClick={props.onNext} disabled={props.currentPage >= props.totalPages}>
          Next →
        </button>
      </div>
    </div>
  );
}

function ProfileTable({ rows }: { rows: CostByProfileRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="card">
        <div className="empty-state">No profile rollup yet (no sessions recorded).</div>
      </div>
    );
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Profiles ({rows.length})</h3>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Profile</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Sessions</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Tokens in</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Tokens out</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>USD</th>
            <th style={thStyle}>Last used</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.profile_name}>
              <td style={tdStyle}>{r.profile_name}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(r.sessions_count)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(r.total_tokens_in)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(r.total_tokens_out)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>${fmtUsd(r.total_usd)}</td>
              <td style={tdStyle}>{shortDate(r.last_used_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TicketTable({ rows }: { rows: CostByTicketRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="card">
        <div className="empty-state">No ticket-bound sessions yet.</div>
      </div>
    );
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Tickets ({rows.length})</h3>
      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Ticket</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Sessions</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Tokens in</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Tokens out</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>USD</th>
            <th style={thStyle}>Last activity</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ticket_id}>
              <td style={tdStyle}>#{r.ticket_id}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(r.sessions_count)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(r.total_tokens_in)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{fmtNum(r.total_tokens_out)}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>${fmtUsd(r.total_usd)}</td>
              <td style={tdStyle}>{shortDate(r.last_used_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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

// ── Helpers ───────────────────────────────────────────────────────────

/** Fill missing days with zero rows so the chart x-axis stays continuous. */
function fillTrendGaps(rows: CostByDayRow[], windowDays: number): CostByDayRow[] {
  const byDate = new Map(rows.map((r) => [r.date, r]));
  const out: CostByDayRow[] = [];
  const today = new Date();
  for (let i = windowDays - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setUTCDate(today.getUTCDate() - i);
    const key = d.toISOString().slice(0, 10); // YYYY-MM-DD
    const existing = byDate.get(key);
    out.push(
      existing || {
        date: key,
        tokens_in: 0,
        tokens_out: 0,
        sessions_count: 0,
        usd: 0,
      },
    );
  }
  return out;
}
