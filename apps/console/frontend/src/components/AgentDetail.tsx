import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  getAgent,
  getAgentInbox,
  getAgentSent,
  getAgentTickets,
} from '../api';
import type { Agent, AgentMessage, Ticket } from '../types';

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [inbox, setInbox] = useState<AgentMessage[]>([]);
  const [sent, setSent] = useState<AgentMessage[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    Promise.all([
      getAgent(id),
      getAgentTickets(id),
      getAgentInbox(id),
      getAgentSent(id),
    ])
      .then(([a, t, i, s]) => {
        setAgent(a);
        setTickets(t.tickets);
        setInbox(i.messages);
        setSent(s.messages);
      })
      .catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <div className="error">{error}</div>;
  if (!agent) return <p className="loading">Loading agent…</p>;

  return (
    <div>
      <div className="page-header">
        <h2>
          <span className={`dot ${agent.tmux_status}`} /> {agent.id}
        </h2>
        <Link to="/agents" className="subtitle">← back to all agents</Link>
      </div>

      <div className="grid grid-3">
        <div className="card">
          <h3>Identity</h3>
          <div style={{ fontSize: 13 }}>
            <div><strong>Role:</strong> {agent.role || '—'}</div>
            <div><strong>Project:</strong> {agent.project || '—'}</div>
            <div><strong>Stream:</strong> {agent.work_stream || '—'}</div>
            <div><strong>Type:</strong> {agent.agent_type}</div>
            <div><strong>Tmux:</strong> {agent.tmux_status}</div>
          </div>
        </div>
        <div className="card">
          <h3>Workload</h3>
          <div style={{ fontSize: 13 }}>
            <div><strong>{agent.workload.in_progress}</strong> in progress</div>
            <div><strong>{agent.workload.new}</strong> new</div>
            <div><strong>{agent.workload.blocked}</strong> blocked</div>
          </div>
        </div>
        <div className="card">
          <h3>Profile</h3>
          {agent.profile ? (
            <div style={{ fontSize: 12 }}>
              <div className="metric-sub">updated {agent.profile.updated_at}</div>
              <div style={{ marginTop: 6 }}>{agent.profile.current_context || '—'}</div>
            </div>
          ) : (
            <div className="empty-state" style={{ padding: 8 }}>no profile</div>
          )}
        </div>
      </div>

      <section className="detail-section" style={{ marginTop: 20 }}>
        <h3>Tickets ({tickets.length})</h3>
        {tickets.length === 0 ? (
          <div className="empty-state">no tickets assigned</div>
        ) : (
          <div className="board">
            <div className="board-column">
              <h4>Active</h4>
              {tickets.filter((t) => t.status === 4 || t.status === 3 || t.status === 1).map((t) => (
                <div className="ticket-card" key={t.id}>
                  <span className="id">#{t.id}</span>
                  <span className={`pri ${t.priority || 'low'}`}>{t.priority}</span>
                  <div style={{ marginTop: 4 }}>{t.headline}</div>
                  <div className="assignee">status={t.status}</div>
                </div>
              ))}
            </div>
            <div className="board-column">
              <h4>Done / archived</h4>
              {tickets.filter((t) => t.status === 0 || t.status === -1).slice(0, 10).map((t) => (
                <div className="ticket-card" key={t.id}>
                  <span className="id">#{t.id}</span>
                  <div style={{ marginTop: 4 }}>{t.headline}</div>
                  <div className="assignee">status={t.status}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="detail-section">
        <h3>Inbox (recent {inbox.length})</h3>
        {inbox.length === 0 ? (
          <div className="empty-state">empty inbox</div>
        ) : (
          <ul className="message-list">
            {inbox.map((m) => (
              <li key={m.id}>
                <div className="meta">
                  #{m.id} · from <strong>{m.from_agent}</strong> · {m.created_at}
                  {m.read_at ? ' · read' : ' · unread'}
                </div>
                <div className="body">{m.body}</div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="detail-section">
        <h3>Sent (recent {sent.length})</h3>
        {sent.length === 0 ? (
          <div className="empty-state">no sent messages</div>
        ) : (
          <ul className="message-list">
            {sent.map((m) => (
              <li key={m.id}>
                <div className="meta">
                  #{m.id} · to <strong>{m.to_agent}</strong> · {m.created_at}
                </div>
                <div className="body">{m.body}</div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
