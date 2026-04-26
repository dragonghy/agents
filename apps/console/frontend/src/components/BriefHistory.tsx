import { useEffect, useState } from 'react';
import { getBrief, listBriefs } from '../api';
import type { BriefSummary } from '../types';

export default function BriefHistory() {
  const [briefs, setBriefs] = useState<BriefSummary[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  useEffect(() => {
    if (!selectedDate) return;
    setContent('');
    getBrief(selectedDate)
      .then((r) => setContent(r.markdown))
      .catch((e) => setError(String(e)));
  }, [selectedDate]);

  if (loading) return <p className="loading">Loading briefs…</p>;
  if (error) return <div className="error">{error}</div>;
  if (!briefs.length) return <div className="empty-state">No briefs yet.</div>;

  return (
    <div>
      <div className="page-header">
        <h2>Brief History</h2>
        <span className="subtitle">{briefs.length} briefs on disk</span>
      </div>
      <div className="grid grid-2" style={{ gridTemplateColumns: '240px 1fr' }}>
        <div className="card">
          <h3>Recent</h3>
          <ul className="brief-list">
            {briefs.map((b) => (
              <li key={b.date}>
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    setSelectedDate(b.date);
                  }}
                  style={{
                    fontWeight: b.date === selectedDate ? 700 : 400,
                  }}
                >
                  {b.date}
                </a>
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                  {(b.size_bytes / 1024).toFixed(1)} kB
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h3>{selectedDate || '—'}</h3>
          <div className="brief-content">{content || 'Select a date.'}</div>
        </div>
      </div>
    </div>
  );
}
