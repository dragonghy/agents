/**
 * TicketBoard — top-level Tickets page (Task #20).
 *
 * Owns:
 * - The Board/List mode toggle (Finding #1).
 * - The workspace dropdown filter used by both modes (Finding #3 — workspace
 *   is now a per-page filter, not a global sidebar switcher).
 *
 * Board mode renders the existing kanban grouping (NEW / IN PROGRESS / BLOCKED).
 * List mode renders <TicketList> (Workspace > Project > umbrella > children).
 *
 * Cards in Board mode are clickable links to /tickets/:id.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTicketBoard, listWorkspaces } from '../api';
import type { BoardColumn, Workspace } from '../types';
import TicketList from './TicketList';

const REFRESH_MS = 15000;
type Mode = 'board' | 'list';

const WORKSPACE_STORAGE_KEY = 'console.tickets.workspace';
const MODE_STORAGE_KEY = 'console.tickets.mode';

function readStoredWorkspace(): number | null {
  try {
    const v = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (v === null || v === 'all') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function readStoredMode(): Mode {
  try {
    const v = localStorage.getItem(MODE_STORAGE_KEY);
    if (v === 'list') return 'list';
  } catch {
    // ignore
  }
  return 'board';
}

export default function TicketBoard() {
  const [mode, setMode] = useState<Mode>(readStoredMode);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(readStoredWorkspace);

  // Workspaces list (for filter dropdown).
  useEffect(() => {
    listWorkspaces()
      .then((r) => {
        setWorkspaces(r.workspaces);
        // If we don't have a stored selection, default to the first 'work'
        // workspace (or the first workspace if no 'work' kind).
        if (workspaceId === null && r.workspaces.length > 0) {
          // Don't auto-pick; keep "All" as the default for v1.
        }
      })
      .catch(() => {
        // Non-fatal — filter dropdown just won't be populated.
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onChangeWorkspace(v: string) {
    if (v === 'all') {
      setWorkspaceId(null);
      try {
        localStorage.setItem(WORKSPACE_STORAGE_KEY, 'all');
      } catch {
        // ignore
      }
      return;
    }
    const n = Number(v);
    if (Number.isFinite(n)) {
      setWorkspaceId(n);
      try {
        localStorage.setItem(WORKSPACE_STORAGE_KEY, String(n));
      } catch {
        // ignore
      }
    }
  }

  function onChangeMode(m: Mode) {
    setMode(m);
    try {
      localStorage.setItem(MODE_STORAGE_KEY, m);
    } catch {
      // ignore
    }
  }

  const workspaceLabel = useMemo(() => {
    if (workspaceId === null) return 'All workspaces';
    const w = workspaces.find((x) => x.id === workspaceId);
    return w ? w.name : `workspace #${workspaceId}`;
  }, [workspaceId, workspaces]);

  return (
    <div>
      <div className="page-header">
        <h2>Tickets · {workspaceLabel}</h2>
        <span className="subtitle">
          {mode === 'board' ? 'kanban · refreshes every 15s' : 'tree · refreshes every 30s'}
        </span>
      </div>

      <div
        className="card"
        style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}
      >
        <div role="tablist" style={{ display: 'inline-flex', gap: 4 }}>
          <ModeButton
            active={mode === 'board'}
            onClick={() => onChangeMode('board')}
          >
            Board
          </ModeButton>
          <ModeButton
            active={mode === 'list'}
            onClick={() => onChangeMode('list')}
          >
            List
          </ModeButton>
        </div>
        <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
          Workspace:&nbsp;
          <select
            value={workspaceId === null ? 'all' : String(workspaceId)}
            onChange={(e) => onChangeWorkspace(e.target.value)}
          >
            <option value="all">All</option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {mode === 'board' ? (
        <BoardMode workspaceId={workspaceId} />
      ) : (
        <TicketList workspaceId={workspaceId} />
      )}
    </div>
  );
}

function BoardMode({ workspaceId }: { workspaceId: number | null }) {
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
      {totalTickets === 0 && (
        <div className="empty-state">
          {workspaceId === null
            ? 'No active tickets across all workspaces.'
            : `No active tickets for workspace ${workspaceId}.`}
        </div>
      )}
      <div className="board">
        {columns.map((c) => (
          <div className="board-column" key={c.status}>
            <h4>
              {c.label} · {c.tickets.length}
            </h4>
            {c.tickets.map((t) => (
              <Link
                key={t.id}
                to={`/tickets/${t.id}`}
                className="ticket-card"
                style={{
                  display: 'block',
                  textDecoration: 'none',
                  color: 'inherit',
                }}
              >
                <span className="id">#{t.id}</span>
                <span className={`pri ${t.priority || 'low'}`}>{t.priority}</span>
                <div style={{ marginTop: 4 }}>{t.headline}</div>
                <div className="assignee">→ {t.assignee || 'unassigned'}</div>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      style={{
        background: active ? 'var(--bg-panel-hover)' : 'transparent',
        color: active ? 'var(--text)' : 'var(--text-dim)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        padding: '4px 12px',
        cursor: 'pointer',
        fontSize: 12,
        fontWeight: active ? 600 : 400,
      }}
    >
      {children}
    </button>
  );
}
