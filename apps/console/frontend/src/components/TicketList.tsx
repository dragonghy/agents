/**
 * TicketList — hierarchical Workspace > Project > umbrella > children view.
 *
 * Sibling to the kanban Board view (Task #20 Finding #1).
 *
 * Reads from /api/v1/orchestration/tickets/tree, indents children by one
 * level (deeper nesting requires drilling into a ticket's detail page).
 *
 * Filters: a single workspace dropdown is owned by the parent (TicketBoard);
 * we just receive a `workspaceId` prop and re-fetch when it changes.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTicketTree } from '../api';
import type {
  TicketSummary,
  TicketTreeResponse,
  TicketTreeWorkspace,
} from '../types';

const REFRESH_MS = 30_000;

interface Props {
  workspaceId: number | null;
}

const STATUS_LABEL: Record<number, string> = {
  4: 'WIP',
  3: 'NEW',
  1: 'BLOCKED',
  0: 'DONE',
  [-1]: 'ARCHIVED',
};
const STATUS_COLOR: Record<number, string> = {
  4: '#facc15',
  3: '#60a5fa',
  1: '#f87171',
  0: '#94a3b8',
  [-1]: '#64748b',
};

export default function TicketList({ workspaceId }: Props) {
  const [tree, setTree] = useState<TicketTreeWorkspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const load = () => {
      getTicketTree(workspaceId)
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
  }, [workspaceId]);

  if (loading && tree.length === 0) return <p className="loading">Loading tickets…</p>;
  if (error) return <div className="error">{error}</div>;

  if (tree.length === 0)
    return <div className="empty-state">No tickets in tree view.</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {tree.map((ws) => (
        <WorkspaceBlock key={ws.workspace.id ?? 'unassigned'} block={ws} />
      ))}
    </div>
  );
}

function WorkspaceBlock({ block }: { block: TicketTreeWorkspace }) {
  const totalTickets = block.projects.reduce(
    (acc, p) => acc + p.tickets.length + p.tickets.reduce((a, t) => a + t.children.length, 0),
    0,
  );
  return (
    <div className="card">
      <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>{block.workspace.name}</span>
        {block.workspace.kind && (
          <span style={kindBadgeStyle}>{block.workspace.kind}</span>
        )}
        <span
          style={{
            marginLeft: 'auto',
            fontSize: 11,
            color: 'var(--text-muted)',
            fontWeight: 400,
          }}
        >
          {totalTickets} ticket(s)
        </span>
      </h3>
      {block.projects.length === 0 ? (
        <div className="empty-state">No tickets.</div>
      ) : (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {block.projects.map((p) => (
            <ProjectBlock
              key={`${p.project.id ?? 'none'}`}
              projectName={p.project.name}
              projectId={p.project.id}
              tickets={p.tickets}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectBlock({
  projectName,
  projectId,
  tickets,
}: {
  projectName: string | null;
  projectId: number | null;
  tickets: { ticket: TicketSummary; children: TicketSummary[] }[];
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          marginBottom: 4,
          fontWeight: 600,
        }}
      >
        {projectName || (projectId ? `Project #${projectId}` : 'No project')}
      </div>
      {tickets.length === 0 ? (
        <div className="empty-state">No tickets in this project.</div>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {tickets.map((item) => (
            <TicketRowWithChildren key={item.ticket.id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}

function TicketRowWithChildren({
  item,
}: {
  item: { ticket: TicketSummary; children: TicketSummary[] };
}) {
  return (
    <li style={{ marginBottom: 4 }}>
      <TicketRow ticket={item.ticket} indent={0} />
      {item.children.length > 0 && (
        <ul style={{ listStyle: 'none', margin: 0, paddingLeft: 0 }}>
          {item.children.map((c) => (
            <li key={c.id}>
              <TicketRow ticket={c} indent={1} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function TicketRow({ ticket, indent }: { ticket: TicketSummary; indent: number }) {
  const status = ticket.status ?? 0;
  const label = STATUS_LABEL[status] || String(status);
  const color = STATUS_COLOR[status] || 'var(--text-muted)';
  return (
    <Link
      to={`/tickets/${ticket.id}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '4px 8px',
        marginLeft: indent * 20,
        borderLeft: `3px solid ${color}`,
        background: 'var(--bg)',
        textDecoration: 'none',
        color: 'var(--text)',
        fontSize: 13,
      }}
    >
      <code style={{ fontSize: 11, color: 'var(--text-dim)' }}>#{ticket.id}</code>
      <span
        style={{
          fontSize: 10,
          color,
          fontWeight: 600,
          minWidth: 60,
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      <span style={{ flex: 1 }}>{ticket.headline}</span>
      {ticket.priority && ticket.priority !== 'low' && (
        <span style={priorityChipStyle(ticket.priority)}>{ticket.priority}</span>
      )}
      {ticket.assignee && (
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
          → {ticket.assignee}
        </span>
      )}
    </Link>
  );
}

function priorityChipStyle(priority: string): React.CSSProperties {
  const palette: Record<string, string> = {
    high: '#f87171',
    medium: '#facc15',
    low: '#94a3b8',
    urgent: '#ef4444',
  };
  const c = palette[priority] || 'var(--text-muted)';
  return {
    fontSize: 10,
    color: c,
    border: `1px solid ${c}`,
    borderRadius: 3,
    padding: '0 4px',
    textTransform: 'uppercase',
  };
}

const kindBadgeStyle: React.CSSProperties = {
  fontSize: 10,
  color: 'var(--text-muted)',
  border: '1px solid var(--border)',
  borderRadius: 3,
  padding: '0 6px',
  textTransform: 'uppercase',
  fontWeight: 400,
};
