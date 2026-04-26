import { useEffect, useState } from 'react';
import { getCostSummary } from '../api';
import type { CostSummary } from '../types';

interface Props {
  compact?: boolean;
}

const REFRESH_MS = 30000;

function fmt(n: number): string {
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function CostDashboard({ compact = false }: Props) {
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      getCostSummary()
        .then((r) => {
          if (cancelled) return;
          setData(r);
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          setError(String(e));
        });
    };
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="loading">Loading cost summary…</p>;

  return (
    <div>
      {!compact && (
        <div className="page-header">
          <h2>Cost Dashboard</h2>
          <span className="subtitle">refreshes every 30s</span>
        </div>
      )}

      <div className="grid grid-3">
        <div className="card">
          <h3>Today</h3>
          <div className="metric-big">${fmt(data.today_usd)}</div>
          <div className="metric-sub">
            {data.today_input_tokens.toLocaleString()} in /{' '}
            {data.today_output_tokens.toLocaleString()} out
          </div>
        </div>
        <div className="card">
          <h3>Last 7 days</h3>
          <div className="metric-big">${fmt(data.week_usd)}</div>
          <div className="metric-sub">rolling window</div>
        </div>
        <div className="card">
          <h3>Lifetime</h3>
          <div className="metric-big">${fmt(data.lifetime_usd)}</div>
          <div className="metric-sub">
            {data.lifetime_input_tokens.toLocaleString()} in /{' '}
            {data.lifetime_output_tokens.toLocaleString()} out
          </div>
        </div>
      </div>

      {!compact && (
        <>
          <div className="card" style={{ marginTop: 16 }}>
            <h3>By agent (lifetime)</h3>
            {data.by_agent.length === 0 ? (
              <div className="empty-state">no usage recorded yet</div>
            ) : (
              data.by_agent.map((a) => (
                <div className="cost-rank" key={a.agent_id}>
                  <span className="agent">{a.agent_id}</span>
                  <span>
                    today ${fmt(a.today_usd)} · week ${fmt(a.week_usd)} · lifetime $
                    {fmt(a.lifetime_usd)} · {a.lifetime_messages.toLocaleString()} msgs
                  </span>
                </div>
              ))
            )}
          </div>

          <div className="refresh-note">
            {data.pricing.note} Input ${data.pricing.input_per_million}/M, Output $
            {data.pricing.output_per_million}/M, Cache R/W $
            {data.pricing.cache_read_per_million}/M / ${data.pricing.cache_write_per_million}/M.
          </div>
        </>
      )}
    </div>
  );
}
