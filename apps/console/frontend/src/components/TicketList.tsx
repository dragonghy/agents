/**
 * TicketList — hierarchical Workspace > Project > umbrella > children view.
 *
 * Sibling to the kanban Board view. Receives ``workspaceId`` (from the
 * page-level dropdown) plus a ``statuses`` allow-list (from the toolbar
 * status chips) and ``priorityFilter`` / ``search`` so all four filters
 * apply consistently across Board and List modes.
 *
 * Reads from /api/v1/orchestration/tickets/tree, indents children by one
 * level (deeper nesting requires drilling into a ticket's detail page).
 */
import { useEffect, useMemo, useState } from 'react';
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
  statuses?: number[];
  priorities?: string[];
  search?: string;
  tagFilter?: string;
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

const DEFAULT_STATUSES = [3, 4, 1]; // active set: New / WIP / Blocked

export default function TicketList({
  workspaceId,
  statuses = DEFAULT_STATUSES,
  priorities,
  search = '',
  tagFilter = '',
}: Props) {
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

  // Apply status / priority / search / tag filters client-side. The server
  // returns the full tree (the backend tree endpoint doesn't take a status
  // query param yet — see task #46), and filtering it here keeps the
  // toolbar 1:1 between Board and List views.
  const filteredTree = useMemo(() => {
    const q = search.trim().toLowerCase();
    const tagQ = tagFilter.trim().toLowerCase();
    function matchesTicket(t: TicketSummary): boolean {
      const status = t.status ?? 0;
      if (!statuses.includes(status)) return false;
      const pri = t.priority || 'medium';
      if (priorities && priorities.length > 0 && !priorities.includes(pri)) {
        return false;
      }
      if (tagQ && !(t.tags || '').toLowerCase().includes(tagQ)) return false;
      if (q) {
        const hit =
          String(t.id).includes(q) ||
          (t.headline || '').toLowerCase().includes(q) ||
          (t.tags || '').toLowerCase().includes(q);
        if (!hit) return false;
      }
      return true;
    }
    return tree
      .map((ws) => ({
        ...ws,
        projects: ws.projects
          .map((p) => ({
            ...p,
            tickets: p.tickets
              .map((item) => ({
                ticket: item.ticket,
                children: item.children.filter(matchesTicket),
              }))
              // Keep umbrella ticket if it matches OR if it has any
              // matching children (so a DONE umbrella with active
              // children doesn't disappear). For pure DONE/Archived
              // umbrellas with no matching kids, drop the row.
              .filter(
                (item) =>
                  matchesTicket(item.ticket) || item.children.length > 0
              ),
          }))
          .filter((p) => p.tickets.length > 0),
      }))
      .filter((ws) => ws.projects.length > 0);
  }, [tree, statuses, priorities, search, tagFilter]);

  if (loading && tree.length === 0) return <p className="loading">Loading tickets…</p>;
  if (error) return <div className="error">{error}</div>;

  if (filteredTree.length === 0) {
    return (
      <div className="empty-state">
        No tickets match the current filters.
        {tree.length > 0 && ' Try widening Status or clearing the search box.'}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {filteredTree.map((ws) => (
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
      <div className="project-block-label">
        {projectName || (projectId ? `Project #${projectId}` : 'No project')}
        <span className="project-block-count">{tickets.length}</span>
      </div>
      <ul className="ticket-tree">
        {tickets.map((item) => (
          <TicketRowWithChildren key={item.ticket.id} item={item} />
        ))}
      </ul>
    </div>
  );
}

function TicketRowWithChildren({
  item,
}: {
  item: { ticket: TicketSummary; children: TicketSummary[] };
}) {
  return (
    <li>
      <TicketRow ticket={item.ticket} indent={0} />
      {item.children.length > 0 && (
        <ul className="ticket-tree-children">
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
      className="tree-row"
      style={{
        marginLeft: indent * 20,
        borderLeftColor: color,
      }}
    >
      <code className="tree-row-id">#{ticket.id}</code>
      <span className="tree-row-status" style={{ color }}>
        {label}
      </span>
      <span className="tree-row-headline">{ticket.headline || '(no headline)'}</span>
      {ticket.priority && ticket.priority !== 'low' && (
        <span className={`pri pri-${ticket.priority}`}>{ticket.priority}</span>
      )}
    </Link>
  );
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
