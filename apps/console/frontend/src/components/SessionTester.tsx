/**
 * SessionTester — minimum viable test harness for orchestration v1
 * (Task #17). Three sections stacked vertically:
 *
 *   1. Profile picker (fed by GET /api/v1/orchestration/profiles).
 *   2. Session controls (Spawn / Close).
 *   3. Conversation log (textarea + Send).
 *
 * No streaming, no markdown, no fancy UI. Final assistant text only.
 * Talks to the daemon via Vite proxy (see ``vite.config.ts``).
 */
import { useEffect, useState } from 'react';
import {
  appendMessage,
  closeSession,
  listProfiles,
  spawnSession,
} from '../api';
import type { Profile, Session, SessionMessage } from '../types';

const DEFAULT_PROFILE = 'secretary';

export default function SessionTester() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profilesError, setProfilesError] = useState<string | null>(null);
  const [selectedProfile, setSelectedProfile] = useState<string>(DEFAULT_PROFILE);

  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [draft, setDraft] = useState<string>('');

  const [pending, setPending] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Load profile list on mount.
  useEffect(() => {
    listProfiles()
      .then((r) => {
        setProfiles(r.profiles);
        if (r.profiles.length > 0) {
          const has = r.profiles.find((p) => p.name === DEFAULT_PROFILE);
          if (!has) setSelectedProfile(r.profiles[0].name);
        }
      })
      .catch((e) => setProfilesError(String(e)));
  }, []);

  async function onSpawn() {
    setActionError(null);
    setPending(true);
    try {
      const s = await spawnSession({
        profile_name: selectedProfile,
        binding_kind: 'standalone',
      });
      setSession(s);
      setMessages([]);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setPending(false);
    }
  }

  async function onClose() {
    if (!session) return;
    setActionError(null);
    setPending(true);
    try {
      await closeSession(session.id);
      setSession({ ...session, status: 'closed' });
    } catch (e) {
      setActionError(String(e));
    } finally {
      setPending(false);
    }
  }

  async function onSend() {
    if (!session || !draft.trim() || pending) return;
    const text = draft;
    setActionError(null);
    setPending(true);
    setMessages((m) => [
      ...m,
      { role: 'user', text, ts: Date.now() },
    ]);
    setDraft('');
    try {
      const result = await appendMessage(session.id, text);
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: result.assistant_text, ts: Date.now() },
      ]);
    } catch (e) {
      setActionError(String(e));
      // Mark the trailing user message as un-replied so the user sees what
      // didn't go through; the simplest signal is leaving it in the list.
    } finally {
      setPending(false);
    }
  }

  const sessionActive = session && session.status === 'active';

  return (
    <div>
      <div className="page-header">
        <h2>Test Harness</h2>
        <span className="subtitle">
          Phase 1+2 minimum viable verification. Spawn → send → see reply.
        </span>
      </div>

      {/* ── Profile picker ── */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>1. Profile</h3>
        {profilesError && <div className="error">{profilesError}</div>}
        {!profilesError && profiles.length === 0 && (
          <p className="loading">Loading profiles…</p>
        )}
        {profiles.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label htmlFor="profile-pick">Profile:</label>
            <select
              id="profile-pick"
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
              disabled={!!sessionActive || pending}
            >
              {profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} — {p.runner_type}
                </option>
              ))}
            </select>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {profiles.find((p) => p.name === selectedProfile)?.description || ''}
            </span>
          </div>
        )}
      </div>

      {/* ── Session controls ── */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>2. Session</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={onSpawn} disabled={pending || !!sessionActive || !profiles.length}>
            {sessionActive ? 'Session active' : 'Spawn'}
          </button>
          <button onClick={onClose} disabled={pending || !sessionActive}>
            Close
          </button>
          {session && (
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              <code>{session.id}</code> · status={session.status} ·
              profile={session.profile_name} ·
              tokens={session.cost_tokens_in}/{session.cost_tokens_out}
            </span>
          )}
        </div>
      </div>

      {/* ── Conversation log ── */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>3. Conversation</h3>
        {actionError && <div className="error" style={{ marginBottom: 8 }}>{actionError}</div>}
        {!session && (
          <div className="empty-state">No session yet. Spawn one above.</div>
        )}
        {session && messages.length === 0 && (
          <div className="empty-state">Empty. Type something and hit Send.</div>
        )}
        {messages.length > 0 && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
              marginBottom: 12,
              maxHeight: 480,
              overflowY: 'auto',
            }}
          >
            {messages.map((m) => (
              <div
                key={`${m.role}-${m.ts}`}
                style={{
                  background: m.role === 'user' ? 'var(--bg-panel-hover)' : 'var(--bg-panel)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  padding: 8,
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    marginBottom: 4,
                  }}
                >
                  {m.role}
                </div>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{m.text}</div>
              </div>
            ))}
          </div>
        )}
        {session && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={pending || !sessionActive}
              placeholder="Say something to the agent…"
              rows={3}
              style={{
                width: '100%',
                padding: 8,
                background: 'var(--bg)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                fontFamily: 'inherit',
                fontSize: 13,
                resize: 'vertical',
              }}
            />
            <div>
              <button
                onClick={onSend}
                disabled={pending || !sessionActive || !draft.trim()}
              >
                {pending ? 'Sending… (5-30s)' : 'Send'}
              </button>
              {pending && (
                <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                  Calling Claude…
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
