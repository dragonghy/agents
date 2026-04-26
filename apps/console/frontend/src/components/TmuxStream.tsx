import { useEffect, useState } from 'react';
import { captureTmux, listTmuxWindows } from '../api';
import type { TmuxWindow } from '../types';

const SESSION = 'agents';
const REFRESH_MS = 5000;

export default function TmuxStream() {
  const [windows, setWindows] = useState<TmuxWindow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [output, setOutput] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [exists, setExists] = useState<boolean>(true);

  // Load window list once
  useEffect(() => {
    listTmuxWindows(SESSION)
      .then((r) => {
        setWindows(r.windows);
        setExists(r.exists);
        if (r.windows.length > 0 && !selected) setSelected(r.windows[0].name);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll capture when a window is selected
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    const load = () => {
      captureTmux(SESSION, selected, 60)
        .then((r) => {
          if (cancelled) return;
          setOutput(r.output);
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
  }, [selected]);

  return (
    <div>
      <div className="page-header">
        <h2>Tmux Activity Stream</h2>
        <span className="subtitle">read-only · refreshes every 5s · session={SESSION}</span>
      </div>

      {!exists && (
        <div className="error">tmux session "{SESSION}" not running.</div>
      )}

      {windows.length > 0 && (
        <div className="tmux-tabs">
          {windows.map((w) => (
            <button
              key={w.name}
              className={selected === w.name ? 'selected' : ''}
              onClick={() => setSelected(w.name)}
            >
              {w.name}
              {w.active ? ' ●' : ''}
            </button>
          ))}
        </div>
      )}

      {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}

      {selected ? (
        <pre className="tmux-stream">{output || '(no output yet)'}</pre>
      ) : (
        <div className="empty-state">No tmux window selected.</div>
      )}
      <p className="refresh-note">
        Strictly <code>capture-pane -p</code> — no writes, no kills, no resizes.
      </p>
    </div>
  );
}
