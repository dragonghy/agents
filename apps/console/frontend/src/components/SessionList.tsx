/**
 * SessionList — paginated list of all sessions.
 *
 * Filters: status / profile / ticket id / live-search (id, channel,
 * binding). Live indicator: any session that received a streaming
 * chunk in the last 4s gets a pulsing green dot in the row.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { listProfiles, listSessions } from '../api';
import { sseBus } from '../lib/sseBus';
import type { Profile, Session } from '../types';

const REFRESH_MS = 15_000;
const PAGE_SIZE = 50;
const STREAMING_FRESH_MS = 4_000;

export default function SessionList() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [profileFilter, setProfileFilter] = useState<string>('all');
  const [ticketFilter, setTicketFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [offset, setOffset] = useState<number>(0);
  const [lastChunkBySession, setLastChunkBySession] = useState<Record<string, number>>({});

  // Profiles dropdown
  useEffect(() => {
    listProfiles()
      .then((r) => setProfiles(r.profiles))
      .catch(() => {
        /* non-fatal */
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
    const id = setInterval(load, REFRESH_MS);

    const offCreated = sseBus.subscribe('session.created', (ev) => {
      const row = ev.payload as unknown as Session;
      if (!row || !row.id) return;
      if (statusFilter !== 'all' && row.status !== statusFilter) return;
      if (profileFilter !== 'all' && row.profile_name !== profileFilter) return;
      if (Number.isFinite(ticketNum as number) && row.ticket_id !== ticketNum) return;
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
        prev.map((s) => (s.id === p.session_id ? { ...s, status: 'closed' as const } : s))
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
    const offMsg = sseBus.subscribe('session.message_appended', (ev) => {
      const p = ev.payload as { session_id?: string; role?: string };
      if (p.role === 'assistant' && p.session_id) {
        setLastChunkBySession((prev) => ({ ...prev, [p.session_id!]: Date.now() }));
      }
    });

    return () => {
      cancelled = true;
      clearInterval(id);
      offCreated();
      offClosed();
      offCost();
      offMsg();
    };
  }, [statusFilter, profileFilter, ticketFilter, offset]);

  // Drive the live-dot fade with a 1Hz tick.
  const [, forceTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => forceTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / PAGE_SIZE)),
    [total]
  );
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  const q = search.trim().toLowerCase();
  const filteredRows = q
    ? sessions.filter(
        (s) =>
          s.id.toLowerCase().includes(q) ||
          (s.channel_id || '').toLowerCase().includes(q) ||
          (s.binding_kind || '').toLowerCase().includes(q)
      )
    : sessions;

  return (
    <div>
      <div className="page-header">
        <h2>Sessions</h2>
        <span className="subtitle">{total} total · refreshes every 15s</span>
      </div>

      {/* Filters */}
      <div className="card filters-toolbar" style={{ marginBottom: 12 }}>
        <div className="filters-row-1">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setOffset(0);
            }}
            className="filter-select"
          >
            <option value="all">All statuses</option>
            <option value="active">Active only</option>
            <option value="closed">Closed only</option>
          </select>
          <select
            value={profileFilter}
            onChange={(e) => {
              setProfileFilter(e.target.value);
              setOffset(0);
            }}
            className="filter-select"
          >
            <option value="all">All profiles</option>
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="ticket #id"
            value={ticketFilter}
            onChange={(e) => {
              setTicketFilter(e.target.value);
              setOffset(0);
            }}
            className="filter-input-mini"
            style={{ width: 100 }}
          />
          <input
            type="search"
            placeholder="Search id / channel / binding…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="filter-search"
          />
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      {loading && sessions.length === 0 && <p className="loading">Loading sessions…</p>}

      {!loading && filteredRows.length === 0 && !error && (
        <div className="empty-state">No sessions match these filters.</div>
      )}

      {filteredRows.length > 0 && (
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 12 }}>
              Page {currentPage} / {totalPages}
            </h3>
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
              {filteredRows.length} of {sessions.length} on this page
              {q && <em> · search active</em>}
            </span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Profile</th>
                <th>Binding</th>
                <th>Ticket</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Tokens (in / out)</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((s) => {
                const last = lastChunkBySession[s.id] || 0;
                const isStreaming = last > 0 && Date.now() - last < STREAMING_FRESH_MS;
                const isTpm =
                  s.parent_session_id == null && s.profile_name === 'tpm';
                return (
                  <tr key={s.id} className={isTpm ? 'data-row-tpm' : ''}>
                    <td>
                      <Link
                        to={`/sessions/${encodeURIComponent(s.id)}`}
                        className="session-link"
                      >
                        <code>{s.id.slice(0, 30)}{s.id.length > 30 ? '…' : ''}</code>
                      </Link>
                      {isTpm && <span className="tpm-badge">TPM</span>}
                      {isStreaming && (
                        <span
                          title="streaming live"
                          style={{
                            display: 'inline-block',
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            background: 'var(--status-active)',
                            marginLeft: 6,
                            verticalAlign: 'middle',
                            animation: 'streamingPulse 1.2s ease-in-out infinite',
                          }}
                        />
                      )}
                    </td>
                    <td>{s.profile_name}</td>
                    <td className="binding-cell">{s.binding_kind}</td>
                    <td>
                      {s.ticket_id ? (
                        <Link to={`/tickets/${s.ticket_id}`} className="session-link-dim">
                          #{s.ticket_id}
                        </Link>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td>
                      <span className={`session-status status-${s.status}`}>{s.status}</span>
                    </td>
                    <td style={{ textAlign: 'right', fontFamily: 'monospace', fontSize: 11 }}>
                      {(s.cost_tokens_in || 0).toLocaleString()} /{' '}
                      {(s.cost_tokens_out || 0).toLocaleString()}
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {(s.created_at || '').slice(0, 16)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={currentPage <= 1}
              className="btn-secondary btn-sm"
            >
              ← Prev
            </button>
            <button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={currentPage >= totalPages}
              className="btn-secondary btn-sm"
            >
              Next →
            </button>
            <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
              showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
