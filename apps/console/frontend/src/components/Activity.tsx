/**
 * Activity — unified reverse-chrono feed of comments + session events.
 *
 * Filter chips at the top toggle individual event kinds. Each row is a
 * link to the relevant detail page (ticket / session). Cheap polling
 * (every 30s) keeps the feed fresh; future enhancement could push via SSE.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getActivityFeed } from '../api';
import type { ActivityEvent, ActivityKind } from '../api';
import { sseBus } from '../lib/sseBus';

const REFRESH_MS = 30_000;
const PAGE_SIZE = 75;

const KIND_META: Record<
  ActivityKind,
  { label: string; icon: string; color: string }
> = {
  comment: { label: 'Comments', icon: '💬', color: '#60a5fa' },
  session_created: { label: 'Sessions opened', icon: '🆕', color: '#4ade80' },
  session_closed: { label: 'Sessions closed', icon: '🔒', color: '#94a3b8' },
};
const ALL_KINDS: ActivityKind[] = ['comment', 'session_created', 'session_closed'];

export default function Activity() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [active, setActive] = useState<Set<ActivityKind>>(new Set(ALL_KINDS));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await getActivityFeed({
          limit: PAGE_SIZE,
          kinds: active.size === ALL_KINDS.length ? undefined : [...active],
        });
        if (!cancelled) {
          setEvents(r.events);
          setError(null);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      }
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    // SSE: trigger an opportunistic reload when something interesting fires.
    const offCreated = sseBus.subscribe('session.created', () => load());
    const offClosed = sseBus.subscribe('session.closed', () => load());
    return () => {
      cancelled = true;
      clearInterval(id);
      offCreated();
      offClosed();
    };
  }, [active]);

  function toggle(k: ActivityKind) {
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      // Never lock to empty — clicking the last active chip restores all.
      return next.size === 0 ? new Set(ALL_KINDS) : next;
    });
  }

  const grouped = useMemo(() => groupByDay(events), [events]);

  if (loading && events.length === 0)
    return <p className="loading">Loading activity…</p>;
  if (error) return <div className="error">{error}</div>;

  return (
    <div>
      <div className="page-header">
        <h2>Activity</h2>
        <span className="subtitle">
          {events.length} events · refreshes every 30s
        </span>
      </div>

      <div className="card filters-toolbar" style={{ marginBottom: 14 }}>
        <div className="filters-row-1" style={{ flexWrap: 'wrap' }}>
          <span className="filter-group-label">Show:</span>
          {ALL_KINDS.map((k) => {
            const meta = KIND_META[k];
            const on = active.has(k);
            return (
              <button
                key={k}
                onClick={() => toggle(k)}
                className={`filter-chip ${on ? 'filter-chip-active' : ''}`}
                style={
                  on
                    ? { borderColor: meta.color, color: meta.color, background: `${meta.color}15` }
                    : undefined
                }
              >
                <span style={{ marginRight: 6 }}>{meta.icon}</span>
                {meta.label}
              </button>
            );
          })}
        </div>
      </div>

      {events.length === 0 ? (
        <div className="empty-state">No activity in the selected filters.</div>
      ) : (
        <div className="activity-feed">
          {grouped.map(({ day, items }) => (
            <div key={day} className="activity-day">
              <div className="activity-day-label">{day}</div>
              <ul className="activity-list">
                {items.map((ev, i) => (
                  <li key={`${ev.ts}-${i}`}>
                    <Link to={ev.link} className="activity-row">
                      <span className="activity-time">{(ev.ts || '').slice(11, 19)}</span>
                      <span
                        className="activity-icon"
                        style={{ color: KIND_META[ev.kind]?.color }}
                      >
                        {KIND_META[ev.kind]?.icon || '•'}
                      </span>
                      <span className="activity-title">{ev.title}</span>
                      <span className="activity-subtitle">{ev.subtitle}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function groupByDay(events: ActivityEvent[]): { day: string; items: ActivityEvent[] }[] {
  const out: { day: string; items: ActivityEvent[] }[] = [];
  let cur: { day: string; items: ActivityEvent[] } | null = null;
  for (const ev of events) {
    const day = (ev.ts || '').slice(0, 10) || 'unknown';
    if (!cur || cur.day !== day) {
      cur = { day, items: [] };
      out.push(cur);
    }
    cur.items.push(ev);
  }
  return out;
}
