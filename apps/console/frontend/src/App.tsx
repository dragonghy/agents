import { useEffect, useMemo, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import {
  getCostByProfile,
  getCostBySession,
  getCostTotals,
  getTicketBoard,
  listSessions,
  listWorkspaces,
} from './api';
import type {
  CostByProfileRow,
  CostBySessionRow,
  CostTotalsResponse,
  Workspace,
} from './types';
import TicketBoard from './components/TicketBoard';
import BriefHistory from './components/BriefHistory';
import CostDashboard from './components/CostDashboard';
import SessionList from './components/SessionList';
import SessionDetail from './components/SessionDetail';
import SessionTester from './components/SessionTester';
import ProfileList from './components/ProfileList';
import ProfileDetail from './components/ProfileDetail';

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<number>(1);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listWorkspaces()
      .then((r) => setWorkspaces(r.workspaces))
      .catch((e) => setError(String(e)));
  }, []);

  const location = useLocation();

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Console v0.1</h1>
        <nav>
          <NavLink to="/" end className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Overview
          </NavLink>
          <NavLink to="/board" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Ticket Board
          </NavLink>
          <NavLink to="/sessions" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Sessions
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Profiles
          </NavLink>
          <NavLink to="/briefs" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Briefs
          </NavLink>
          <NavLink to="/cost" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Cost
          </NavLink>
          <NavLink to="/test-harness" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Test Harness
          </NavLink>
        </nav>

        <div className="workspace-switcher">
          <label htmlFor="ws-switch">Workspace</label>
          <select
            id="ws-switch"
            value={activeWorkspace}
            onChange={(e) => setActiveWorkspace(Number(e.target.value))}
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </div>

        {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

        <div style={{ marginTop: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
          <p style={{ margin: 0 }}>Read-only Phase 1</p>
          <p style={{ margin: 0 }}>
            <Link to="/" reloadDocument>localhost:3001</Link>
          </p>
          <p style={{ margin: '4px 0 0 0', fontSize: 10 }}>
            Path: <code>{location.pathname}</code>
          </p>
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Overview workspaceId={activeWorkspace} />} />
          <Route path="/board" element={<TicketBoard workspaceId={activeWorkspace} />} />
          <Route path="/sessions" element={<SessionList />} />
          <Route path="/sessions/:id" element={<SessionDetail />} />
          <Route path="/profiles" element={<ProfileList />} />
          <Route path="/profiles/:name" element={<ProfileDetail />} />
          <Route path="/briefs" element={<BriefHistory />} />
          <Route path="/cost" element={<CostDashboard />} />
          <Route path="/test-harness" element={<SessionTester />} />
        </Routes>
      </main>
    </div>
  );
}

function Overview({ workspaceId }: { workspaceId: number }) {
  const [totals, setTotals] = useState<CostTotalsResponse | null>(null);
  const [activeSessionsCount, setActiveSessionsCount] = useState<number>(0);
  const [activeTpmsCount, setActiveTpmsCount] = useState<number>(0);
  const [recentSessions, setRecentSessions] = useState<CostBySessionRow[]>([]);
  const [topProfile, setTopProfile] = useState<CostByProfileRow | null>(null);
  const [boardCounts, setBoardCounts] = useState<{
    new: number;
    wip: number;
    blocked: number;
  }>({ new: 0, wip: 0, blocked: 0 });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [t, active, tpms, recent, byProfile, board] = await Promise.all([
          getCostTotals(),
          listSessions({ status: 'active', limit: 1 }),
          listSessions({ status: 'active', profile: 'tpm', limit: 1 }),
          getCostBySession({ limit: 5 }),
          getCostByProfile(),
          getTicketBoard(workspaceId),
        ]);
        if (cancelled) return;
        setTotals(t);
        setActiveSessionsCount(active.total);
        setActiveTpmsCount(tpms.total);
        setRecentSessions(recent.sessions);
        setTopProfile(byProfile.rollup[0] || null);
        const counts = { new: 0, wip: 0, blocked: 0 };
        for (const c of board.columns) {
          if (c.status === 3) counts.new = c.tickets.length;
          else if (c.status === 4) counts.wip = c.tickets.length;
          else if (c.status === 1) counts.blocked = c.tickets.length;
        }
        setBoardCounts(counts);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(String(e));
      }
    };
    load();
    const id = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [workspaceId]);

  const openTickets = useMemo(
    () => boardCounts.new + boardCounts.wip + boardCounts.blocked,
    [boardCounts]
  );

  return (
    <div>
      <div className="page-header">
        <h2>Overview</h2>
        <span className="subtitle">workspace_id={workspaceId} · refreshes every 30s</span>
      </div>

      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      {/* Header tile row */}
      <div className="grid grid-3" style={{ marginBottom: 12 }}>
        <Tile
          label="Active sessions"
          value={activeSessionsCount.toLocaleString()}
        />
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
          value={openTickets.toLocaleString()}
          sub={`${boardCounts.new} new / ${boardCounts.wip} wip / ${boardCounts.blocked} blocked`}
        />
      </div>
      <div className="grid grid-3" style={{ marginBottom: 12 }}>
        <Tile label="Active TPMs" value={activeTpmsCount.toLocaleString()} />
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
          label="Most active Profile"
          value={topProfile?.profile_name || '—'}
          sub={
            topProfile
              ? `${topProfile.sessions_count} sessions · $${topProfile.total_usd.toFixed(2)}`
              : undefined
          }
        />
      </div>

      {/* Ticket board summary card */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0 }}>Tickets · workspace {workspaceId}</h3>
          <Link to="/board" style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            view full board →
          </Link>
        </div>
        <div className="grid grid-3" style={{ marginTop: 12 }}>
          <CountChip label="New" count={boardCounts.new} color="#60a5fa" />
          <CountChip label="In progress" count={boardCounts.wip} color="#facc15" />
          <CountChip label="Blocked" count={boardCounts.blocked} color="#f87171" />
        </div>
      </div>

      {/* Recent sessions */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0 }}>Recent sessions (last 5)</h3>
          <Link to="/sessions" style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            all sessions →
          </Link>
        </div>
        {recentSessions.length === 0 ? (
          <div className="empty-state">No sessions yet.</div>
        ) : (
          <table style={recentTableStyle}>
            <thead>
              <tr>
                <th style={recentThStyle}>Session</th>
                <th style={recentThStyle}>Profile</th>
                <th style={recentThStyle}>Status</th>
                <th style={{ ...recentThStyle, textAlign: 'right' }}>USD</th>
                <th style={recentThStyle}>Created</th>
              </tr>
            </thead>
            <tbody>
              {recentSessions.map((s) => (
                <tr key={s.id}>
                  <td style={recentTdStyle}>
                    <Link
                      to={`/sessions/${encodeURIComponent(s.id)}`}
                      style={{ color: 'var(--text)', textDecoration: 'underline' }}
                    >
                      <code style={{ fontSize: 11 }}>{s.id}</code>
                    </Link>
                  </td>
                  <td style={recentTdStyle}>{s.profile_name}</td>
                  <td style={recentTdStyle}>{s.status}</td>
                  <td style={{ ...recentTdStyle, textAlign: 'right' }}>
                    ${s.cost_usd.toFixed(2)}
                  </td>
                  <td style={recentTdStyle}>{(s.created_at || '').slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Tile(props: { label: string; value: string; sub?: string }) {
  return (
    <div className="card">
      <div
        style={{
          fontSize: 11,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          marginBottom: 4,
        }}
      >
        {props.label}
      </div>
      <div className="metric-big">{props.value}</div>
      {props.sub && (
        <div className="metric-sub" style={{ marginTop: 4 }}>
          {props.sub}
        </div>
      )}
    </div>
  );
}

function CountChip({
  label,
  count,
  color,
}: {
  label: string;
  count: number;
  color: string;
}) {
  return (
    <div
      style={{
        background: 'var(--bg)',
        border: '1px solid var(--border)',
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        padding: '8px 12px',
      }}
    >
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 600 }}>{count}</div>
    </div>
  );
}

const recentTableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
  marginTop: 8,
};
const recentThStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 8px',
  borderBottom: '1px solid var(--border)',
  color: 'var(--text-dim)',
  fontWeight: 600,
  fontSize: 11,
  textTransform: 'uppercase',
};
const recentTdStyle: React.CSSProperties = {
  padding: '6px 8px',
  borderBottom: '1px solid var(--border)',
};
