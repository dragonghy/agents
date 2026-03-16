import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Agents from './pages/Agents';
import AgentDetail from './pages/AgentDetail';
import Tickets from './pages/Tickets';
import TicketDetail from './pages/TicketDetail';
import Messages from './pages/Messages';
import Feedback from './pages/Feedback';
import Tokens from './pages/Tokens';
import Schedules from './pages/Schedules';
import Onboarding from './pages/Onboarding';
import { fetchOnboardingStatus } from './api/onboarding';

function OnboardingGuard({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);

  useEffect(() => {
    fetchOnboardingStatus()
      .then((status) => {
        setNeedsOnboarding(!status.completed);
      })
      .catch(() => {
        // If status check fails, show dashboard anyway
        setNeedsOnboarding(false);
      })
      .finally(() => setChecking(false));
  }, []);

  if (checking) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center">
        <div className="text-gray-400 dark:text-gray-500">Loading...</div>
      </div>
    );
  }

  if (needsOnboarding) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Onboarding route — outside Layout (no sidebar) */}
        <Route path="/onboarding" element={<Onboarding />} />

        {/* Main app — wrapped in Layout with onboarding guard */}
        <Route
          element={
            <OnboardingGuard>
              <Layout />
            </OnboardingGuard>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/agents/:id" element={<AgentDetail />} />
          <Route path="/tokens" element={<Tokens />} />
          <Route path="/schedules" element={<Schedules />} />
          <Route path="/tickets" element={<Tickets />} />
          <Route path="/tickets/:id" element={<TicketDetail />} />
          <Route path="/messages" element={<Messages />} />
          <Route path="/feedback" element={<Feedback />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
