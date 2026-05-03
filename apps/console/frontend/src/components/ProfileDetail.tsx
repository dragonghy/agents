/**
 * ProfileDetail — drill-in for one Profile (Task #18 Part C).
 *
 * Sections:
 *   1. Frontmatter — runner_type / mcp_servers / skills / orchestration_tools.
 *   2. System prompt — read-only display of the profile.md body.
 *   3. Recent sessions — last 10 sessions for this Profile (link to drill-in).
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getProfile, getProfileSessions } from '../api';
import type { ProfileDetailResponse, Session } from '../types';

export default function ProfileDetail() {
  const { name } = useParams<{ name: string }>();
  const profileName = name || '';

  const [data, setData] = useState<ProfileDetailResponse | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!profileName) return;
    let cancelled = false;
    Promise.all([
      getProfile(profileName).catch((e) => {
        throw e;
      }),
      getProfileSessions(profileName, 10).catch(() => ({
        sessions: [] as Session[],
        total: 0,
        profile_name: profileName,
      })),
    ])
      .then(([d, s]) => {
        if (cancelled) return;
        setData(d);
        setSessions(s.sessions);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profileName]);

  if (loading) return <p className="loading">Loading profile…</p>;
  if (error)
    return (
      <div>
        <div className="error">{error}</div>
        <p>
          <Link to="/profiles">← all profiles</Link>
        </p>
      </div>
    );
  if (!data) return null;

  const { registry, profile } = data;

  return (
    <div>
      <div className="page-header">
        <h2>Profile · {registry.name}</h2>
        <span className="subtitle">
          <Link to="/profiles">← all profiles</Link>
        </span>
      </div>

      {data.error && (
        <div className="error" style={{ marginBottom: 12 }}>{data.error}</div>
      )}

      {/* Frontmatter card */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Frontmatter</h3>
        <div className="grid grid-2">
          <Meta label="Runner" value={<code>{registry.runner_type}</code>} />
          <Meta
            label="Last used"
            value={registry.last_used_at?.slice(0, 19) || '—'}
          />
          <Meta
            label="MCP servers"
            value={
              profile && profile.mcp_servers.length > 0
                ? profile.mcp_servers.join(', ')
                : <span style={{ color: 'var(--text-muted)' }}>none</span>
            }
          />
          <Meta
            label="Skills"
            value={
              profile && profile.skills.length > 0
                ? profile.skills.join(', ')
                : <span style={{ color: 'var(--text-muted)' }}>none</span>
            }
          />
          <Meta
            label="Orchestration tools"
            value={profile?.orchestration_tools ? 'yes (TPM)' : 'no'}
          />
          <Meta
            label="File"
            value={
              <code style={{ fontSize: 11 }}>
                {(profile?.file_path || registry.file_path || '').replace(
                  /^.*\/profiles\//,
                  'profiles/'
                )}
              </code>
            }
          />
        </div>
        <div
          style={{ marginTop: 12, fontSize: 13, color: 'var(--text-dim)' }}
        >
          {registry.description}
        </div>
      </div>

      {/* System prompt body */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>System prompt</h3>
        {profile?.system_prompt ? (
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              padding: 12,
              fontSize: 12,
              fontFamily: 'ui-monospace, Menlo, monospace',
              maxHeight: 500,
              overflowY: 'auto',
              margin: 0,
              color: 'var(--text)',
            }}
          >
            {profile.system_prompt}
          </pre>
        ) : (
          <div className="empty-state">
            File missing or unparseable; system prompt unavailable.
          </div>
        )}
      </div>

      {/* Recent sessions */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Recent sessions ({sessions.length})</h3>
        {sessions.length === 0 ? (
          <div className="empty-state">
            No sessions yet for this Profile.
          </div>
        ) : (
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Session</th>
                <th style={thStyle}>Binding</th>
                <th style={thStyle}>Ticket</th>
                <th style={thStyle}>Status</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Tokens in/out</th>
                <th style={thStyle}>Created</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td style={tdStyle}>
                    <Link
                      to={`/sessions/${encodeURIComponent(s.id)}`}
                      style={{ color: 'var(--text)', textDecoration: 'underline' }}
                    >
                      <code style={{ fontSize: 11 }}>{s.id}</code>
                    </Link>
                  </td>
                  <td style={tdStyle}>{s.binding_kind}</td>
                  <td style={tdStyle}>
                    {s.ticket_id ? `#${s.ticket_id}` : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                  </td>
                  <td style={tdStyle}>{s.status}</td>
                  <td
                    style={{ ...tdStyle, textAlign: 'right', fontFamily: 'monospace', fontSize: 11 }}
                  >
                    {(s.cost_tokens_in || 0).toLocaleString()} /{' '}
                    {(s.cost_tokens_out || 0).toLocaleString()}
                  </td>
                  <td style={tdStyle}>{(s.created_at || '').slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 13 }}>{value}</div>
    </div>
  );
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
};
const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 8px',
  borderBottom: '1px solid var(--border)',
  color: 'var(--text-dim)',
  fontWeight: 600,
  fontSize: 11,
  textTransform: 'uppercase',
};
const tdStyle: React.CSSProperties = {
  padding: '6px 8px',
  borderBottom: '1px solid var(--border)',
};
