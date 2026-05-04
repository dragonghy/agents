/**
 * BriefHistory — read past Morning Briefs.
 *
 * Left rail: list of dates (most recent first). Right pane: rendered
 * brief markdown + cross-links: any ``#NNN`` ticket reference becomes
 * a router link. Plus a search box that filters dates client-side by
 * matching against pre-fetched body text — useful for "did I see X
 * mentioned this week?".
 */
import { useEffect, useMemo, useState } from 'react';
import { getBrief, listBriefs } from '../api';
import Markdown from '../lib/markdown';
import type { BriefSummary } from '../types';

interface CachedBrief {
  date: string;
  markdown: string;
}

export default function BriefHistory() {
  const [briefs, setBriefs] = useState<BriefSummary[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [bodyCache, setBodyCache] = useState<Record<string, string>>({});
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Initial load: list of briefs.
  useEffect(() => {
    listBriefs()
      .then((r) => {
        setBriefs(r.briefs);
        setLoading(false);
        if (r.briefs.length > 0) setSelectedDate(r.briefs[0].date);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
  }, []);

  // Selected brief body fetch.
  useEffect(() => {
    if (!selectedDate) return;
    if (bodyCache[selectedDate]) {
      setContent(bodyCache[selectedDate]);
      return;
    }
    setContent('');
    getBrief(selectedDate)
      .then((r) => {
        setContent(r.markdown);
        setBodyCache((prev) => ({ ...prev, [selectedDate]: r.markdown }));
      })
      .catch((e) => setError(String(e)));
  }, [selectedDate]); // eslint-disable-line react-hooks/exhaustive-deps

  // Search index: lazily fetch all bodies on first non-empty search so
  // we can grep across them. Costly for >100 briefs; we cap at 30.
  useEffect(() => {
    if (!search.trim()) return;
    const toFetch = briefs
      .slice(0, 30)
      .filter((b) => bodyCache[b.date] === undefined)
      .map((b) => b.date);
    if (toFetch.length === 0) return;
    let cancelled = false;
    Promise.all(
      toFetch.map((d) =>
        getBrief(d)
          .then((r) => ({ d, body: r.markdown }))
          .catch(() => ({ d, body: '' })),
      ),
    ).then((rows) => {
      if (cancelled) return;
      setBodyCache((prev) => {
        const next = { ...prev };
        for (const { d, body } of rows) next[d] = body;
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [search, briefs, bodyCache]);

  const filteredBriefs = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return briefs;
    return briefs.filter((b) => {
      const body = bodyCache[b.date];
      if (body === undefined) {
        // Cache miss; show the row but mark it pending so user knows
        // search is still indexing.
        return false;
      }
      return body.toLowerCase().includes(q) || b.date.includes(q);
    });
  }, [briefs, bodyCache, search]);

  if (loading) return <p className="loading">Loading briefs…</p>;
  if (error) return <div className="error">{error}</div>;
  if (!briefs.length) return <div className="empty-state">No briefs yet.</div>;

  // Highlight matches in the rendered markdown is outside scope; the
  // sidebar count tells you how many briefs match the query.
  const isSearching = !!search.trim();

  return (
    <div>
      <div className="page-header">
        <h2>Briefs</h2>
        <span className="subtitle">
          {isSearching
            ? `${filteredBriefs.length} of ${briefs.length} match "${search.trim()}"`
            : `${briefs.length} briefs on disk`}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
        <div>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search across briefs…"
            className="filter-search"
            style={{ width: '100%', marginBottom: 10 }}
          />
          <div className="card" style={{ padding: '10px 12px' }}>
            <ul className="brief-list-v2">
              {(isSearching ? filteredBriefs : briefs).map((b) => (
                <li key={b.date}>
                  <button
                    onClick={() => setSelectedDate(b.date)}
                    className={`brief-list-btn ${
                      b.date === selectedDate ? 'brief-list-btn-active' : ''
                    }`}
                  >
                    <span>{b.date}</span>
                    <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 10 }}>
                      {(b.size_bytes / 1024).toFixed(1)} kB
                    </span>
                  </button>
                </li>
              ))}
              {isSearching && filteredBriefs.length === 0 && (
                <li>
                  <div className="empty-state-tight">
                    {Object.keys(bodyCache).length < briefs.length
                      ? 'Indexing briefs…'
                      : 'No matches.'}
                  </div>
                </li>
              )}
            </ul>
          </div>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>{selectedDate || '—'}</h3>
            {selectedDate && (
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
                rendered with cross-links
              </span>
            )}
          </div>
          {content ? (
            <div className="brief-content-v2">
              <Markdown source={content} variant="block" />
            </div>
          ) : (
            <div className="empty-state">Select a date.</div>
          )}
        </div>
      </div>
    </div>
  );
}
