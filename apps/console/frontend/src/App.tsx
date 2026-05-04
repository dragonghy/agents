import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import Inbox from './components/Inbox';
import TicketBoard from './components/TicketBoard';
import TicketDetail from './components/TicketDetail';
import BriefHistory from './components/BriefHistory';
import CostDashboard from './components/CostDashboard';
import SessionList from './components/SessionList';
import SessionDetail from './components/SessionDetail';
import SessionTester from './components/SessionTester';
import ProfileList from './components/ProfileList';
import ProfileDetail from './components/ProfileDetail';

export default function App() {
  const location = useLocation();

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>Agent Console</h1>
        <nav>
          <NavLink to="/" end className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">📥</span> Inbox
          </NavLink>
          <NavLink to="/board" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">🎫</span> Tickets
          </NavLink>
          <NavLink to="/sessions" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">💬</span> Sessions
          </NavLink>
          <NavLink to="/profiles" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">👥</span> Profiles
          </NavLink>
          <NavLink to="/briefs" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">📰</span> Briefs
          </NavLink>
          <NavLink to="/cost" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">💰</span> Cost
          </NavLink>
          <NavLink to="/test-harness" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            <span className="nav-icon">🧪</span> Test Harness
          </NavLink>
        </nav>

        <div style={{ marginTop: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
          <p style={{ margin: 0 }}>
            <Link to="/" reloadDocument style={{ color: 'var(--text-muted)' }}>
              localhost:3001
            </Link>
          </p>
          <p style={{ margin: '4px 0 0 0', fontSize: 10 }}>
            Path: <code>{location.pathname}</code>
          </p>
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Inbox />} />
          <Route path="/board" element={<TicketBoard />} />
          <Route path="/tickets/:id" element={<TicketDetail />} />
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
