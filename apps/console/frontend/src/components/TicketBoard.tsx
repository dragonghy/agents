import { useEffect, useState } from 'react';
import { getTicketBoard } from '../api';
import type { BoardColumn } from '../types';

interface Props {
  workspaceId: number;
  embedded?: boolean;
}

const REFRESH_MS = 15000;

export default function TicketBoard({ workspaceId, embedded = false }: Props) {
  const [columns, setColumns] = useState<BoardColumn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const load = () => {
      getTicketBoard(workspaceId)
        .then((r) => {
          if (cancelled) return;
          setColumns(r.columns);
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
  }, [workspaceId]);

  if (loading && !columns.length) return <p className="loading">Loading board…</p>;
  if (error) return <div className="error">{error}</div>;

  const totalTickets = columns.reduce((acc, c) => acc + c.tickets.length, 0);

  return (
    <>
      {!embedded && (
        <div className="page-header">
          <h2>Ticket Board · workspace {workspaceId}</h2>
          <span className="subtitle">
            {totalTickets} active · refreshes every 15s
          </span>
        </div>
      )}
      {totalTickets === 0 && (
        <div className="empty-state">
          No active tickets for workspace {workspaceId}.
          {workspaceId === 2 && ' (Personal workspace is currently empty.)'}
        </div>
      )}
      <div className="board">
        {columns.map((c) => (
          <div className="board-column" key={c.status}>
            <h4>
              {c.label} · {c.tickets.length}
            </h4>
            {c.tickets.map((t) => (
              <div className="ticket-card" key={t.id}>
                <span className="id">#{t.id}</span>
                <span className={`pri ${t.priority || 'low'}`}>{t.priority}</span>
                <div style={{ marginTop: 4 }}>{t.headline}</div>
                <div className="assignee">→ {t.assignee || 'unassigned'}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
