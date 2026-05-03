/**
 * SessionList — paginated list of all sessions (Task #18 Part B).
 *
 * Filters: status (active|closed|all), profile_name, ticket_id.
 * Click a row → navigate to /sessions/:id.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { listProfiles, listSessions } from '../api';
import { sseBus } from '../lib/sseBus';
import type { Profile, Session } from '../types';

const REFRESH_MS = 15000;
const PAGE_SIZE = 50;

export default function SessionList() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [profileFilter, setProfileFilter] = useState<string>('all');
  const [ticketFilter, setTicketFilter] = useState<string>('');
  const [offset, setOffset] = useState<number>(0);

  // Load profile list once for the filter dropdown.
  useEffect(() => {
    listProfiles()
      .then((r) => setProfiles(r.profiles))
      .catch(() => {
        // Non-fatal — filter just won't be populated.
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const ticketNum = ticketFilter.trim() ? Number(ticketFilter) : undefined;

    const load = async () => {
      try {
        const r = await listSessions({
          limit: PAGE_SIZE,
          offset,
          status: statusFilter === 'all' ? undefined : statusFilter,
          profile: profileFilter === 'all' ? undefined : profileFilter,
          ticket: Number.isFinite(ticketNum as number) ? ticketNum : undefined,
        });
        if (cancelled) return;
        setSessions(r.sessions);
        setTotal(r.total);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    // Polling kept as a backstop. SSE handlers below merge new rows in
    // immediately so the user sees lifecycle events without waiting.
    const id = setInterval(load, REFRESH_MS);

    const offCreated = sseBus.subscribe('session.created', (ev) => {
      const row = ev.payload as unknown as Session;
      if (!row || !row.id) return;
      // Respect active filters: only insert rows that match.
      if (statusFilter !== 'all' && row.status !== statusFilter) return;
      if (profileFilter !== 'all' && row.profile_name !== profileFilter)
        return;
      if (
        Number.isFinite(ticketNum as number) &&
        row.ticket_id !== ticketNum
      )
        return;
      setSessions((prev) => {
        if (prev.some((s) => s.id === row.id)) return prev;
        return [row, ...prev].slice(0, PAGE_SIZE);
      });
      setTotal((t) => t + 1);
    });
    const offClosed = sseBus.subscribe('session.closed', (ev) => {
      const p = ev.payload as { session_id?: string };
      if (!p.session_id) return;
      setSessions((prev) =>
        prev.map((s) =>
          s.id === p.session_id ? { ...s, status: 'closed' as const } : s
        )
      );
    });
    const offCost = sseBus.subscribe('session.cost_updated', (ev) => {
      const p = ev.payload as {
        session_id?: string;
        cost_tokens_in?: number;
        cost_tokens_out?: number;
      };
      if (!p.session_id) return;
      setSessions((prev) =>
        prev.map((s) =>
          s.id === p.session_id
            ? {
                ...s,
                cost_tokens_in: p.cost_tokens_in ?? s.cost_tokens_in,
                cost_tokens_out: p.cost_tokens_out ?? s.cost_tokens_out,
              }
            : s
        )
      );
    });

    return () => {
      cancelled = true;
      clearInterval(id);
      offCreated();
      offClosed();
      offCost();
    };
  }, [statusFilter, profileFilter, ticketFilter, offset]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / PAGE_SIZE)),
    [total]
  );
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <div className="page-header">
        <h2>Sessions</h2>
        <span className="subtitle">
          {total} total · refreshes every 15s
        </span>
      </div>

      {/* Filters */}
      <div
        className="card"
        style={{ marginBottom: 12, display: 'flex', gap: 12, flexWrap: 'wrap' }}
      >
        <label style={filterLabelStyle}>
          Status:&nbsp;
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">all</option>
            <option value="active">active</option>
            <option value="closed">closed</option>
          </select>
        </label>
        <label style={filterLabelStyle}>
          Profile:&nbsp;
          <select
            value={profileFilter}
            onChange={(e) => {
              setProfileFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">all</option>
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label style={filterLabelStyle}>
          Ticket:&nbsp;
          <input
            type="text"
            placeholder="#id"
            value={ticketFilter}
            onChange={(e) => {
              setTicketFilter(e.target.value);
              setOffset(0);
            }}
            style={{ width: 80 }}
          />
        </label>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && sessions.length === 0 && <p className="loading">Loading sessions…</p>}

      {!loading && sessions.length === 0 && !error && (
        <div className="empty-state">No sessions match these filters.</div>
      )}

      {sessions.length > 0 && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>
            Page {currentPage} / {totalPages}
          </h3>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Session</th>
                <th style={thStyle}>Profile</th>
                <th style={thStyle}>Binding</th>
                <th style={thStyle}>Ticket</th>
                <th style={thStyle}>Status</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Tokens</th>
                <th style={thStyle}>Created</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td style={tdStyle}>
                    <Link
                      to={`/sessions/${encodeURIComponent(s.id)}`}
                      style={{ color: 'var(--text)', textDecoration: 'underline' }}
                    >
                      <code style={{ fontSize: 11 }}>{s.id}</code>
                    </Link>
                  </td>
                  <td style={tdStyle}>{s.profile_name}</td>
                  <td style={tdStyle}>{s.binding_kind}</td>
                  <td style={tdStyle}>
                    {s.ticket_id ? `#${s.ticket_id}` : <span style={dimStyle}>—</span>}
                  </td>
                  <td style={tdStyle}>
                    <StatusBadge status={s.status} />
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right', fontFamily: 'monospace', fontSize: 11 }}>
                    {(s.cost_tokens_in || 0).toLocaleString()} /{' '}
                    {(s.cost_tokens_out || 0).toLocaleString()}
                  </td>
                  <td style={tdStyle}>{(s.created_at || '').slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={currentPage <= 1}
            >
              ← Prev
            </button>
            <button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={currentPage >= totalPages}
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === 'active' ? '#4ade80' : 'var(--text-muted)';
  return (
    <span style={{ color, fontWeight: 600, fontSize: 12 }}>{status}</span>
  );
}

const filterLabelStyle: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text-dim)',
};
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
const dimStyle: React.CSSProperties = {
  color: 'var(--text-muted)',
};
