/**
 * TicketBoard — top-level Tickets page.
 *
 * Owns:
 *  - Board / List mode toggle
 *  - Filter toolbar: workspace, status (multi), priority (multi), assignee,
 *    tag, full-text search
 *  - "+ New ticket" inline composer (slides down from the toolbar)
 *  - Kanban renderer (this file). List view is delegated to <TicketList>.
 *
 * State persisted to localStorage so the operator's view survives reloads.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  createTicket,
  getTicketBoard,
  listWorkspaces,
  patchTicket,
} from '../api';
import type { BoardColumn, TicketSummary, Workspace } from '../types';
import TicketList from './TicketList';

const REFRESH_MS = 15_000;
type Mode = 'board' | 'list';

const LS_KEYS = {
  workspace: 'console.tickets.workspace',
  mode: 'console.tickets.mode',
  statuses: 'console.tickets.statuses', // comma-sep status numbers
  priorities: 'console.tickets.priorities',
  tag: 'console.tickets.tag',
};

const ALL_PRIORITIES = ['urgent', 'high', 'medium', 'low'];
const ALL_STATUSES: Array<{ value: number; label: string; color: string }> = [
  { value: 4, label: 'In Progress', color: '#facc15' },
  { value: 3, label: 'New', color: '#60a5fa' },
  { value: 1, label: 'Blocked', color: '#f87171' },
];

function readLS(k: string): string {
  try {
    return localStorage.getItem(k) || '';
  } catch {
    return '';
  }
}
function writeLS(k: string, v: string) {
  try {
    localStorage.setItem(k, v);
  } catch {
    // ignore
  }
}
function readWorkspace(): number | null {
  const v = readLS(LS_KEYS.workspace);
  if (!v || v === 'all') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function readMode(): Mode {
  return readLS(LS_KEYS.mode) === 'list' ? 'list' : 'board';
}
function readStatuses(): number[] {
  const v = readLS(LS_KEYS.statuses);
  if (!v) return [3, 4, 1]; // default = all active
  return v
    .split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isFinite(n));
}
function readPriorities(): string[] {
  const v = readLS(LS_KEYS.priorities);
  if (!v) return ALL_PRIORITIES;
  return v.split(',').filter(Boolean);
}

export default function TicketBoard() {
  const [mode, setMode] = useState<Mode>(readMode);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(readWorkspace);
  const [statuses, setStatuses] = useState<number[]>(readStatuses);
  const [priorities, setPriorities] = useState<string[]>(readPriorities);
  const [tagFilter, setTagFilter] = useState<string>(() => readLS(LS_KEYS.tag));
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [showCreate, setShowCreate] = useState(false);

  // Workspaces dropdown
  useEffect(() => {
    listWorkspaces()
      .then((r) => setWorkspaces(r.workspaces))
      .catch(() => {
        /* non-fatal */
      });
  }, []);

  function onChangeWorkspace(v: string) {
    if (v === 'all') {
      setWorkspaceId(null);
      writeLS(LS_KEYS.workspace, 'all');
      return;
    }
    const n = Number(v);
    if (Number.isFinite(n)) {
      setWorkspaceId(n);
      writeLS(LS_KEYS.workspace, String(n));
    }
  }

  function onChangeMode(m: Mode) {
    setMode(m);
    writeLS(LS_KEYS.mode, m);
  }

  function toggleStatus(s: number) {
    const next = statuses.includes(s)
      ? statuses.filter((x) => x !== s)
      : [...statuses, s];
    setStatuses(next.length ? next : [3, 4, 1]); // never lock to empty
    writeLS(LS_KEYS.statuses, next.join(','));
  }

  function togglePriority(p: string) {
    const next = priorities.includes(p)
      ? priorities.filter((x) => x !== p)
      : [...priorities, p];
    setPriorities(next.length ? next : ALL_PRIORITIES);
    writeLS(LS_KEYS.priorities, next.join(','));
  }

  function clearFilters() {
    setStatuses([3, 4, 1]);
    setPriorities(ALL_PRIORITIES);
    setTagFilter('');
    setSearchQuery('');
    writeLS(LS_KEYS.statuses, '');
    writeLS(LS_KEYS.priorities, '');
    writeLS(LS_KEYS.tag, '');
  }

  const workspaceLabel = useMemo(() => {
    if (workspaceId === null) return 'All workspaces';
    const w = workspaces.find((x) => x.id === workspaceId);
    return w ? w.name : `workspace #${workspaceId}`;
  }, [workspaceId, workspaces]);

  const isFiltered =
    statuses.length !== 3 ||
    priorities.length !== ALL_PRIORITIES.length ||
    !!tagFilter ||
    !!searchQuery;

  return (
    <div>
      <div className="page-header">
        <h2>Tickets · {workspaceLabel}</h2>
        <span className="subtitle">
          {mode === 'board' ? 'kanban · refreshes every 15s' : 'tree · refreshes every 30s'}
        </span>
      </div>

      {/* Toolbar */}
      <div className="card filters-toolbar" style={{ marginBottom: 12 }}>
        <div className="filters-row-1">
          <div role="tablist" className="mode-toggle">
            <ModeButton active={mode === 'board'} onClick={() => onChangeMode('board')}>
              Board
            </ModeButton>
            <ModeButton active={mode === 'list'} onClick={() => onChangeMode('list')}>
              List
            </ModeButton>
          </div>

          <select
            value={workspaceId === null ? 'all' : String(workspaceId)}
            onChange={(e) => onChangeWorkspace(e.target.value)}
            className="filter-select"
          >
            <option value="all">All workspaces</option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>

          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search headline / id / tags… (live)"
            className="filter-search"
          />

          <button
            onClick={() => setShowCreate((s) => !s)}
            className={showCreate ? 'btn-secondary btn-sm' : 'btn-primary btn-sm'}
            style={{ marginLeft: 'auto' }}
          >
            {showCreate ? 'Cancel' : '+ New ticket'}
          </button>
        </div>

        <div className="filters-row-2">
          <FilterGroup label="Status">
            {ALL_STATUSES.map((s) => (
              <FilterChip
                key={s.value}
                active={statuses.includes(s.value)}
                onClick={() => toggleStatus(s.value)}
                color={s.color}
              >
                {s.label}
              </FilterChip>
            ))}
          </FilterGroup>

          <FilterGroup label="Priority">
            {ALL_PRIORITIES.map((p) => (
              <FilterChip
                key={p}
                active={priorities.includes(p)}
                onClick={() => togglePriority(p)}
              >
                {p}
              </FilterChip>
            ))}
          </FilterGroup>

          <input
            type="search"
            value={tagFilter}
            onChange={(e) => {
              setTagFilter(e.target.value);
              writeLS(LS_KEYS.tag, e.target.value);
            }}
            placeholder="tag…"
            className="filter-input-mini"
          />

          {isFiltered && (
            <button onClick={clearFilters} className="btn-secondary btn-sm">
              Clear filters
            </button>
          )}
        </div>

        {showCreate && (
          <CreatePanel
            workspaceId={workspaceId}
            onCreated={(id) => {
              setShowCreate(false);
              // navigate handled inside CreatePanel
            }}
          />
        )}
      </div>

      {mode === 'board' ? (
        <BoardMode
          workspaceId={workspaceId}
          statuses={statuses}
          priorities={priorities}
          tagFilter={tagFilter}
          searchQuery={searchQuery}
        />
      ) : (
        <TicketList
          workspaceId={workspaceId}
          statuses={statuses}
          priorities={priorities}
          search={searchQuery}
          tagFilter={tagFilter}
        />
      )}
    </div>
  );
}

// ── Board mode ────────────────────────────────────────────────────────

function BoardMode({
  workspaceId,
  statuses,
  priorities,
  tagFilter,
  searchQuery,
}: {
  workspaceId: number | null;
  statuses: number[];
  priorities: string[];
  tagFilter: string;
  searchQuery: string;
}) {
  const [columns, setColumns] = useState<BoardColumn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<string>('');

  const refresh = () =>
    getTicketBoard(workspaceId)
      .then((r) => {
        setColumns(r.columns);
        setError(null);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const load = async () => {
      try {
        const r = await getTicketBoard(workspaceId);
        if (cancelled) return;
        setColumns(r.columns);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [workspaceId]);

  // Drop selections that no longer exist (e.g. moved out of view by
  // workspace switch or bulk-status into a hidden column).
  useEffect(() => {
    const visibleIds = new Set<number>();
    for (const c of columns) for (const t of c.tickets) visibleIds.add(t.id);
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => visibleIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [columns]);

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function clearSelection() {
    setSelected(new Set());
  }

  async function bulkPatch(
    body: Parameters<typeof patchTicket>[1],
    label: string,
  ) {
    if (bulkBusy || selected.size === 0) return;
    setBulkBusy(true);
    setError(null);
    const ids = [...selected];
    try {
      let done = 0;
      for (const id of ids) {
        setBulkProgress(`${label}: ${++done} / ${ids.length}`);
        try {
          await patchTicket(id, body);
        } catch (e) {
          // Don't abort the batch — capture and continue. Errors get
          // shown collectively at the end.
          setError(`#${id}: ${String(e)}`);
        }
      }
      setBulkProgress('');
      clearSelection();
      await refresh();
    } finally {
      setBulkBusy(false);
    }
  }

  if (loading && !columns.length) return <p className="loading">Loading board…</p>;
  if (error && !columns.length) return <div className="error">{error}</div>;

  const q = searchQuery.trim().toLowerCase();
  const tagQ = tagFilter.trim().toLowerCase();

  function passesFilters(t: TicketSummary): boolean {
    if (!priorities.includes(t.priority || 'medium')) return false;
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

  // Filter columns by status selection + apply per-card filters.
  const visibleColumns = columns
    .filter((c) => statuses.includes(c.status))
    .map((c) => ({
      ...c,
      tickets: c.tickets.filter(passesFilters),
    }));

  const totalVisible = visibleColumns.reduce((acc, c) => acc + c.tickets.length, 0);

  if (totalVisible === 0) {
    return (
      <div className="empty-state">
        No tickets match the current filters.
        {workspaceId !== null && ' Try widening to "All workspaces".'}
      </div>
    );
  }

  return (
    <>
      {selected.size > 0 && (
        <BulkActionBar
          count={selected.size}
          busy={bulkBusy}
          progress={bulkProgress}
          onClear={clearSelection}
          onChangeStatus={(s) =>
            bulkPatch({ status: s }, `Setting status to ${s}`)
          }
          onChangePriority={(p) =>
            bulkPatch({ priority: p }, `Setting priority to ${p}`)
          }
          onArchive={() =>
            bulkPatch({ status: -1 }, 'Archiving')
          }
        />
      )}
      <div className="board">
        {visibleColumns.map((c) => {
          const status = ALL_STATUSES.find((s) => s.value === c.status);
          const accent = status?.color || 'var(--text-muted)';
          return (
            <div className="board-column" key={c.status}>
              <h4 style={{ borderBottom: `2px solid ${accent}` }}>
                <span style={{ color: accent }}>{c.label}</span>
                <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 11 }}>
                  {c.tickets.length}
                </span>
              </h4>
              {c.tickets.length === 0 ? (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 8 }}>
                  <em>(filtered out)</em>
                </div>
              ) : (
                c.tickets.map((t) => (
                  <BoardCard
                    key={t.id}
                    ticket={t}
                    accent={accent}
                    selected={selected.has(t.id)}
                    onToggle={() => toggleOne(t.id)}
                  />
                ))
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ── Board card ────────────────────────────────────────────────────────

function BoardCard({
  ticket,
  accent,
  selected,
  onToggle,
}: {
  ticket: TicketSummary;
  accent: string;
  selected: boolean;
  onToggle: () => void;
}) {
  const priority = ticket.priority || 'low';
  return (
    <div
      className={`ticket-card-v2 ${selected ? 'ticket-card-v2-selected' : ''}`}
      style={{ borderLeftColor: accent }}
    >
      <div className="ticket-card-row">
        {/* Checkbox is its own click target — clicking it doesn't navigate. */}
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          className="ticket-card-checkbox"
          aria-label={`Select ticket #${ticket.id}`}
        />
        <Link to={`/tickets/${ticket.id}`} className="ticket-card-id-link">
          <span className="ticket-card-id">#{ticket.id}</span>
        </Link>
        <span className={`pri pri-${priority}`}>{priority}</span>
        {ticket.type && ticket.type !== 'task' && (
          <span className="ticket-type-chip">{ticket.type}</span>
        )}
        {ticket.workspace_name && (
          <span className="ticket-card-ws" style={{ marginLeft: 'auto' }}>
            {ticket.workspace_name}
          </span>
        )}
      </div>
      <Link to={`/tickets/${ticket.id}`} className="ticket-card-body-link">
        <div className="ticket-card-headline">{ticket.headline || '(no headline)'}</div>
        {ticket.tags && (
          <div className="ticket-card-tags">
            {ticket.tags
              .split(',')
              .filter((t) => t.trim() && !t.trim().startsWith('agent:'))
              .slice(0, 3)
              .map((t, i) => (
                <span key={i} className="tag-mini">
                  {t.trim()}
                </span>
              ))}
          </div>
        )}
      </Link>
    </div>
  );
}

// ── Bulk action bar ───────────────────────────────────────────────────

function BulkActionBar({
  count,
  busy,
  progress,
  onClear,
  onChangeStatus,
  onChangePriority,
  onArchive,
}: {
  count: number;
  busy: boolean;
  progress: string;
  onClear: () => void;
  onChangeStatus: (s: number) => void;
  onChangePriority: (p: string) => void;
  onArchive: () => void;
}) {
  return (
    <div className="bulk-action-bar">
      <span className="bulk-count">
        <strong>{count}</strong> selected
      </span>
      <span className="bulk-divider" />
      <span className="bulk-label">Status:</span>
      {[
        { v: 4, label: 'In Progress', color: '#facc15' },
        { v: 3, label: 'New', color: '#60a5fa' },
        { v: 1, label: 'Blocked', color: '#f87171' },
        { v: 0, label: 'Done', color: '#4ade80' },
      ].map((s) => (
        <button
          key={s.v}
          onClick={() => onChangeStatus(s.v)}
          disabled={busy}
          className="bulk-btn"
          style={{ color: s.color, borderColor: s.color }}
        >
          {s.label}
        </button>
      ))}
      <span className="bulk-divider" />
      <span className="bulk-label">Priority:</span>
      {ALL_PRIORITIES.map((p) => (
        <button
          key={p}
          onClick={() => onChangePriority(p)}
          disabled={busy}
          className="bulk-btn"
        >
          {p}
        </button>
      ))}
      <span className="bulk-divider" />
      <button
        onClick={onArchive}
        disabled={busy}
        className="bulk-btn bulk-btn-danger"
      >
        Archive
      </button>
      <button
        onClick={onClear}
        disabled={busy}
        className="btn-secondary btn-sm"
        style={{ marginLeft: 'auto' }}
      >
        Clear
      </button>
      {busy && (
        <span className="bulk-progress">
          {progress || 'working…'}
        </span>
      )}
    </div>
  );
}

// ── Create panel ──────────────────────────────────────────────────────

function CreatePanel({
  workspaceId,
  onCreated,
}: {
  workspaceId: number | null;
  onCreated: (id: number) => void;
}) {
  const [headline, setHeadline] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('medium');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const navigate = useNavigate();

  async function onSubmit() {
    if (!headline.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await createTicket({
        headline: headline.trim(),
        description: description.trim() || undefined,
        priority,
        workspace_id: workspaceId ?? undefined,
      });
      onCreated(r.ticket.id);
      navigate(`/tickets/${r.ticket.id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="create-panel">
      <input
        autoFocus
        value={headline}
        onChange={(e) => setHeadline(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') onSubmit();
        }}
        placeholder="Headline (required)…"
        className="filter-search"
        style={{ flex: 1 }}
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)…"
        rows={2}
        className="composer-textarea"
        style={{ marginTop: 8 }}
      />
      <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          className="filter-select"
        >
          {ALL_PRIORITIES.map((p) => (
            <option key={p} value={p}>
              priority: {p}
            </option>
          ))}
        </select>
        <button
          onClick={onSubmit}
          disabled={busy || !headline.trim()}
          className="btn-primary btn-sm"
        >
          {busy ? 'Creating…' : 'Create ticket (⌘+Enter)'}
        </button>
        {err && <span style={{ color: 'var(--status-blocked)', fontSize: 12 }}>{err}</span>}
      </div>
    </div>
  );
}

// ── Tiny components ───────────────────────────────────────────────────

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
      className={`mode-button ${active ? 'mode-button-active' : ''}`}
    >
      {children}
    </button>
  );
}

function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="filter-group">
      <span className="filter-group-label">{label}:</span>
      {children}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  color,
  children,
}: {
  active: boolean;
  onClick: () => void;
  color?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
      style={
        active && color
          ? { borderColor: color, color: color, background: `${color}15` }
          : undefined
      }
    >
      {children}
    </button>
  );
}
