import { useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { listWorkspaces } from './api';
import type { Workspace } from './types';
import TicketBoard from './components/TicketBoard';
import BriefHistory from './components/BriefHistory';
import CostDashboard from './components/CostDashboard';
import SessionTester from './components/SessionTester';

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
          <Route path="/briefs" element={<BriefHistory />} />
          <Route path="/cost" element={<CostDashboard />} />
          <Route path="/test-harness" element={<SessionTester />} />
        </Routes>
      </main>
    </div>
  );
}

function Overview({ workspaceId }: { workspaceId: number }) {
  return (
    <div>
      <div className="page-header">
        <h2>Overview</h2>
        <span className="subtitle">workspace_id={workspaceId}</span>
      </div>
      <div className="grid grid-2">
        <div className="card">
          <h3>Cost (today / week / lifetime)</h3>
          <CostDashboard compact />
        </div>
      </div>
      <div style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Ticket Board — workspace {workspaceId}</h3>
          <TicketBoard workspaceId={workspaceId} embedded />
        </div>
      </div>
    </div>
  );
}
