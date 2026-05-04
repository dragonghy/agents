/**
 * Settings — read-only system info + config inspection.
 *
 * Shows daemon health (uptime, pid, DB size), profile registry summary,
 * known MCP servers from agents.yaml, and the Telegram allow-list. All
 * mutations are still file-edit-and-restart (TELEGRAM_HUMAN_CHAT_ID via
 * .env, profile.md via filesystem) — but at least you can SEE the
 * current state in one place without grepping config files.
 *
 * Future: add an "Add chat" form that POSTs to a new endpoint that
 * appends to .env + signals the bot to reload (task #53 ambition).
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMCPHealth, getSystemInfo } from '../api';
import type { MCPHealth, SystemInfo } from '../api';

export default function Settings() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [health, setHealth] = useState<MCPHealth[]>([]);
  const [healthLoading, setHealthLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await getSystemInfo();
        if (!cancelled) {
          setInfo(r);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    };
    load();
    const id = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  async function runHealthCheck() {
    setHealthLoading(true);
    try {
      const r = await getMCPHealth();
      setHealth(r.checks);
    } catch (e) {
      setError(String(e));
    } finally {
      setHealthLoading(false);
    }
  }

  // Auto-check on first mount.
  useEffect(() => {
    runHealthCheck();
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!info) return <p className="loading">Loading system info…</p>;

  return (
    <div>
      <div className="page-header">
        <h2>Settings</h2>
        <span className="subtitle">read-only · refreshes every 30s</span>
      </div>

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <Tile
          label="Daemon uptime"
          value={fmtDuration(info.uptime_seconds)}
          sub={`pid ${info.pid}`}
        />
        <Tile
          label="Profiles loaded"
          value={String(info.profiles_loaded ?? '—')}
          sub={`${info.sessions_lifetime ?? 0} lifetime sessions`}
        />
        <Tile
          label="Task DB"
          value={info.db_size_bytes != null ? fmtBytes(info.db_size_bytes) : '—'}
          sub=".agents-mcp.db"
        />
      </div>

      {/* ── Profiles ── */}
      <div className="card section-card" style={{ marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>Profile registry</h3>
        {info.profiles.length === 0 ? (
          <div className="empty-state">No profiles loaded.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Runner</th>
                <th>Last used</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {info.profiles.map((p) => (
                <tr key={p.name}>
                  <td>
                    <Link to={`/profiles/${p.name}`} className="session-link">
                      <strong>{p.name}</strong>
                    </Link>
                  </td>
                  <td>{p.runner_type}</td>
                  <td style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                    {p.last_used_at ? p.last_used_at.slice(0, 16) : <em>never</em>}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <Link to={`/profiles/${p.name}`} className="btn-secondary btn-sm">
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
          To add or edit a profile: drop a <code>profile.md</code> under{' '}
          <code>profiles/&lt;name&gt;/</code> and restart the daemon.
        </div>
      </div>

      {/* ── MCP servers ── */}
      <div className="card section-card" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>MCP servers</h3>
          <button
            onClick={runHealthCheck}
            disabled={healthLoading}
            className="btn-secondary btn-sm"
            style={{ marginLeft: 'auto' }}
          >
            {healthLoading ? 'Checking…' : 'Re-check health'}
          </button>
        </div>
        {info.mcp_servers.length === 0 ? (
          <div className="empty-state">No MCP servers configured.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Scope</th>
                <th>Status</th>
                <th>Command</th>
              </tr>
            </thead>
            <tbody>
              {info.mcp_servers.map((m) => {
                const h = health.find((x) => x.name === m.name);
                return (
                  <tr key={`${m.scope}-${m.name}`}>
                    <td>
                      <code>{m.name}</code>
                    </td>
                    <td>
                      <span
                        className={`session-status status-${m.scope === 'personal' ? 'active' : 'closed'}`}
                      >
                        {m.scope}
                      </span>
                    </td>
                    <td>
                      <HealthBadge health={h} />
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)' }}>
                      {m.command || '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* Inline FAIL details for any unhealthy MCPs */}
        {health.some((h) => h.status === 'fail') && (
          <div className="mcp-fails">
            {health
              .filter((h) => h.status === 'fail')
              .map((h) => (
                <div key={h.name} className="mcp-fail-detail">
                  <div className="mcp-fail-name">
                    <strong>{h.name}</strong> — failed
                  </div>
                  <div className="mcp-fail-msg">{h.message}</div>
                  {h.hint && <div className="mcp-fail-hint">💡 {h.hint}</div>}
                </div>
              ))}
          </div>
        )}

        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
          <strong>Personal</strong> MCPs are scoped to the housekeeper profile.{' '}
          <strong>Global</strong> MCPs are available to every agent. Edit{' '}
          <code>agents.yaml</code> + restart daemon to change.{' '}
          <strong>Health checks</strong> only run for personal MCPs (each ships
          a <code>--check</code> mode).
        </div>
      </div>

      {/* ── Telegram ── */}
      <div className="card section-card">
        <h3 style={{ marginTop: 0 }}>Telegram allow-list</h3>
        {info.telegram.allowed_chat_ids.length === 0 ? (
          <div className="empty-state">
            No chat ids allow-listed. Set <code>TELEGRAM_HUMAN_CHAT_ID</code> in{' '}
            <code>.env</code> and restart the bot.
          </div>
        ) : (
          <ul className="allowlist">
            {info.telegram.allowed_chat_ids.map((id) => {
              const isPrimary = id === info.telegram.primary_chat_id;
              const isGroup = id.startsWith('-');
              return (
                <li key={id}>
                  <code>{id}</code>
                  <span className={`tag-mini ${isGroup ? 'tag-group' : 'tag-private'}`}>
                    {isGroup ? 'group' : 'private'}
                  </span>
                  {isPrimary && <span className="tpm-badge">PRIMARY</span>}
                </li>
              );
            })}
          </ul>
        )}
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)' }}>
          To add a chat: append the chat_id to{' '}
          <code>TELEGRAM_HUMAN_CHAT_ID</code> in <code>.env</code> (comma-separated)
          and restart the bot via{' '}
          <code>pkill -f telegram-bot &amp;&amp; nohup uv run --directory services/telegram-bot python bot.py …</code>.
          Group ids are negative; get them from bot logs (an unallow-listed group
          message is logged as <em>"Ignoring message from unknown chat: &lt;id&gt;"</em>).
        </div>
      </div>
    </div>
  );
}

function HealthBadge({ health }: { health?: MCPHealth }) {
  if (!health) {
    return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  }
  const colors: Record<MCPHealth['status'], string> = {
    ok: 'var(--status-active)',
    fail: 'var(--status-blocked)',
    unknown: 'var(--text-muted)',
  };
  const labels: Record<MCPHealth['status'], string> = {
    ok: '✓ ok',
    fail: '✗ fail',
    unknown: '? unknown',
  };
  return (
    <span
      style={{
        color: colors[health.status],
        fontWeight: 600,
        fontSize: 12,
      }}
      title={health.message}
    >
      {labels[health.status]}
    </span>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card">
      <div className="card-tile-label">{label}</div>
      <div className="metric-big">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) {
    const rem = m - h * 60;
    return rem ? `${h}h ${rem}m` : `${h}h`;
  }
  const d = Math.floor(h / 24);
  const remH = h - d * 24;
  return remH ? `${d}d ${remH}h` : `${d}d`;
}

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
