/**
 * ProfileList — registered Profiles overview (Task #18 Part C).
 *
 * Reads ``GET /api/v1/orchestration/profiles`` and renders one card per
 * Profile. Click → drill to /profiles/:name. Shows runner_type + last-used
 * timestamp at a glance to make 4.6 vs 4.7 mismatches obvious.
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listProfiles } from '../api';
import type { Profile } from '../types';

export default function ProfileList() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listProfiles()
      .then((r) => {
        setProfiles(r.profiles);
        setLoading(false);
      })
      .catch((e) => {
        setError(String(e));
        setLoading(false);
      });
  }, []);

  if (loading) return <p className="loading">Loading profiles…</p>;
  if (error) return <div className="error">{error}</div>;

  return (
    <div>
      <div className="page-header">
        <h2>Profiles</h2>
        <span className="subtitle">{profiles.length} registered</span>
      </div>

      {profiles.length === 0 ? (
        <div className="empty-state">
          No profiles registered. Drop a profile.md under ``profiles/&lt;name&gt;/``
          and restart the daemon.
        </div>
      ) : (
        <div className="grid grid-2">
          {profiles.map((p) => (
            <ProfileCard key={p.name} profile={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProfileCard({ profile }: { profile: Profile }) {
  return (
    <Link
      to={`/profiles/${encodeURIComponent(profile.name)}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
    >
      <div
        className="card"
        style={{ cursor: 'pointer', height: '100%' }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>{profile.name}</h3>
        <div
          style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}
        >
          <code>{profile.runner_type}</code>
        </div>
        <div
          style={{
            fontSize: 12,
            color: 'var(--text-dim)',
            lineHeight: 1.4,
          }}
        >
          {profile.description.slice(0, 240)}
          {profile.description.length > 240 ? '…' : ''}
        </div>
        <div
          style={{
            marginTop: 12,
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 10,
            color: 'var(--text-muted)',
          }}
        >
          <span>loaded {(profile.loaded_at || '').slice(0, 16)}</span>
          {profile.last_used_at && (
            <span>last used {profile.last_used_at.slice(0, 16)}</span>
          )}
        </div>
      </div>
    </Link>
  );
}
