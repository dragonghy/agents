import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listAgents } from '../api';
import type { Agent } from '../types';

interface Props {
  compact?: boolean;
}

const REFRESH_MS = 10000;

export default function AgentPanel({ compact = false }: Props) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      listAgents()
        .then((data) => {
          if (cancelled) return;
          setAgents(data);
          setError(null);
          setLoading(false);
        })
        .catch((e) => {
          if (cancelled) return;
          setError(String(e));
          setLoading(false);
        });
    };
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  if (loading && !agents.length) return <p className="loading">Loading agents…</p>;
  if (error) return <div className="error">{error}</div>;
  if (!agents.length) return <div className="empty-state">No agents registered</div>;

  return (
    <>
      {!compact && (
        <div className="page-header">
          <h2>Agents</h2>
          <span className="subtitle">{agents.length} registered · refreshes every 10s</span>
        </div>
      )}
      <div className="grid grid-4">
        {agents.map((a) => (
          <Link
            key={a.id}
            to={`/agents/${a.id}`}
            className="card agent-card"
            style={{ textDecoration: 'none', color: 'inherit' }}
          >
            <div className="agent-id">
              <span className={`dot ${a.tmux_status}`} title={a.tmux_status} />
              {a.id}
            </div>
            <div className="agent-role">{a.role || '—'}</div>
            <div className="workload">
              <span><strong>{a.workload.in_progress}</strong> in-prog</span>
              <span><strong>{a.workload.new}</strong> new</span>
              <span><strong>{a.workload.blocked}</strong> blocked</span>
            </div>
            {a.profile?.current_context && (
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  marginTop: 4,
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {a.profile.current_context}
              </div>
            )}
          </Link>
        ))}
      </div>
      {!compact && <p className="refresh-note">Click an agent for inbox / sent / tickets.</p>}
    </>
  );
}
