/**
 * Workspaces — per-workspace dashboard.
 *
 * Each workspace card shows: ticket counts by status (NEW / WIP /
 * BLOCKED / DONE), project list with per-project ticket counts,
 * and shortcuts to filtered Board/List views. Useful for "what's
 * the state of SnowFlower?" without applying filters by hand.
 *
 * Data source: ``/api/v1/orchestration/tickets/tree`` returns the
 * full structure already. We compute the rollups client-side.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTicketTree } from '../api';
import type {
  TicketSummary,
  TicketTreeResponse,
  TicketTreeWorkspace,
} from '../types';

const STATUS_LABEL: Record<number, { label: string; color: string }> = {
  4: { label: 'In Progress', color: '#facc15' },
  3: { label: 'New', color: '#60a5fa' },
  1: { label: 'Blocked', color: '#f87171' },
  0: { label: 'Done', color: '#4ade80' },
  [-1]: { label: 'Archived', color: '#64748b' },
};
const VISIBLE_STATUSES = [4, 3, 1, 0];

const REFRESH_MS = 30_000;

export default function Workspaces() {
  const [tree, setTree] = useState<TicketTreeWorkspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      getTicketTree(null)
        .then((r: TicketTreeResponse) => {
          if (cancelled) return;
          setTree(r.workspaces);
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

  if (loading && tree.length === 0)
    return <p className="loading">Loading workspaces…</p>;
  if (error) return <div className="error">{error}</div>;

  return (
    <div>
      <div className="page-header">
        <h2>Workspaces</h2>
        <span className="subtitle">{tree.length} workspaces · refreshes every 30s</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {tree.map((ws) => (
          <WorkspaceCard key={ws.workspace.id ?? 'unassigned'} block={ws} />
        ))}
      </div>
    </div>
  );
}

function WorkspaceCard({ block }: { block: TicketTreeWorkspace }) {
  // Flatten tickets + children for status counts.
  const allTickets = useMemo(() => {
    const out: TicketSummary[] = [];
    for (const p of block.projects) {
      for (const item of p.tickets) {
        out.push(item.ticket);
        for (const c of item.children) out.push(c);
      }
    }
    return out;
  }, [block]);

  const counts = useMemo(() => {
    const c: Record<number, number> = { 4: 0, 3: 0, 1: 0, 0: 0, [-1]: 0 };
    for (const t of allTickets) {
      const s = t.status ?? 0;
      c[s] = (c[s] || 0) + 1;
    }
    return c;
  }, [allTickets]);

  const projectCount = block.projects.filter((p) => p.project.id !== null).length;
  const wsId = block.workspace.id;

  return (
    <div className="card workspace-card">
      <div className="workspace-card-header">
        <h3 style={{ margin: 0 }}>
          {block.workspace.name}
        </h3>
        {block.workspace.kind && (
          <span className="ws-kind-badge">{block.workspace.kind}</span>
        )}
        <span className="ws-summary-stats">
          {allTickets.length} ticket(s) · {projectCount} project(s)
        </span>
        {wsId !== null && (
          <Link
            to="/board"
            onClick={() => {
              try {
                localStorage.setItem('console.tickets.workspace', String(wsId));
                localStorage.setItem('console.tickets.mode', 'list');
              } catch {
                /* ignore */
              }
            }}
            className="btn-secondary btn-sm"
            style={{ marginLeft: 'auto' }}
          >
            Open in list →
          </Link>
        )}
      </div>

      {/* Status histogram chips */}
      <div className="ws-status-row">
        {VISIBLE_STATUSES.map((s) => {
          const meta = STATUS_LABEL[s];
          const n = counts[s] || 0;
          return (
            <div
              key={s}
              className="ws-status-chip"
              style={{ borderLeftColor: meta.color }}
            >
              <span className="ws-status-label" style={{ color: meta.color }}>
                {meta.label}
              </span>
              <span className="ws-status-n">{n}</span>
            </div>
          );
        })}
      </div>

      {/* Projects list */}
      {block.projects.length === 0 ? (
        <div className="empty-state-tight">No tickets in this workspace yet.</div>
      ) : (
        <div className="ws-projects">
          <div className="ws-projects-label">Projects</div>
          {block.projects.map((p) => {
            const projectTotal =
              p.tickets.length +
              p.tickets.reduce((acc, item) => acc + item.children.length, 0);
            const wipCount = countByStatus(p, 4);
            const blockedCount = countByStatus(p, 1);
            return (
              <div className="ws-project-row" key={p.project.id ?? 'none'}>
                <div className="ws-project-name">
                  {p.project.id ? (
                    <Link
                      to={`/tickets/${p.project.id}`}
                      className="session-link"
                    >
                      {p.project.name || `Project #${p.project.id}`}
                    </Link>
                  ) : (
                    <em style={{ color: 'var(--text-muted)' }}>(no project)</em>
                  )}
                </div>
                <div className="ws-project-counts">
                  <span>
                    <strong>{projectTotal}</strong> total
                  </span>
                  {wipCount > 0 && (
                    <span style={{ color: STATUS_LABEL[4].color }}>
                      {wipCount} wip
                    </span>
                  )}
                  {blockedCount > 0 && (
                    <span style={{ color: STATUS_LABEL[1].color }}>
                      {blockedCount} blocked
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function countByStatus(
  proj: { tickets: { ticket: TicketSummary; children: TicketSummary[] }[] },
  status: number,
): number {
  let n = 0;
  for (const item of proj.tickets) {
    if ((item.ticket.status ?? 0) === status) n++;
    for (const c of item.children) {
      if ((c.status ?? 0) === status) n++;
    }
  }
  return n;
}
