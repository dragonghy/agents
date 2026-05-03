/**
 * SseBus — singleton EventSource wrapper for orchestration v1 live events.
 *
 * One process-wide ``EventSource`` is shared by every component that wants
 * live updates. Each subscriber filters by event ``kind`` and gets only
 * the events it cares about.
 *
 * Why a singleton: opening one ``EventSource`` per component would create
 * N TCP connections, blow past the browser's per-origin connection cap,
 * and trigger N replays of the ring buffer on connect. One connection,
 * many listeners is the standard SSE pattern.
 *
 * Why no manual reconnect logic: the native ``EventSource`` reconnects
 * automatically with exponential backoff, and on each reconnect the
 * browser sends ``Last-Event-ID`` set to the id of the last received
 * event. Combined with the daemon's ring buffer, that closes any gap
 * for free. Don't reinvent this — just trust the platform.
 *
 * Event shape on the wire:
 *
 *     id: 43\n
 *     event: session.message_appended\n
 *     data: {"id":43,"kind":"session.message_appended","ts":"...","payload":{...}}\n
 *     \n
 *
 * The ``id`` field is what the browser stores and echoes back; the
 * ``data`` field is the JSON we hand to listeners.
 *
 * Wiring: any component that wants live updates calls
 * ``sseBus.subscribe(kind, fn)`` and stores the returned ``unsubscribe``
 * function. ``sseBus.ensureConnected()`` is idempotent and safe to call
 * from multiple places.
 *
 * If SSE is unavailable (network error, daemon down), components keep
 * working — they all have polling fallbacks. SSE is additive, not
 * required.
 */

export interface SseEventPayload {
  id: number;
  kind: string;
  ts: string;
  payload: Record<string, unknown>;
}

type Listener = (event: SseEventPayload) => void;

const ENDPOINT = '/api/v1/orchestration/events';

class SseBus {
  private es: EventSource | null = null;
  private listeners: Map<string, Set<Listener>> = new Map();

  /** Open the EventSource if it isn't already. Idempotent. */
  ensureConnected(): void {
    if (this.es) return;
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      return;
    }
    try {
      this.es = new EventSource(ENDPOINT);
    } catch (err) {
      console.warn('[sseBus] failed to open EventSource:', err);
      return;
    }

    // Each `event:` field in the SSE frame becomes a typed event on the
    // EventSource. We register listeners lazily as subscribers attach
    // (see _attach). Re-attach all currently-known kinds on (re)connect.
    for (const kind of this.listeners.keys()) {
      this._attach(kind);
    }

    this.es.onerror = (err) => {
      // The browser auto-reconnects. We just log so the developer
      // knows when something flaps. No state change here.
      console.warn('[sseBus] EventSource error (auto-reconnect):', err);
    };
  }

  /** Subscribe to events of a given ``kind``. Returns an unsubscribe fn. */
  subscribe(kind: string, fn: Listener): () => void {
    let set = this.listeners.get(kind);
    if (!set) {
      set = new Set();
      this.listeners.set(kind, set);
    }
    set.add(fn);
    this.ensureConnected();
    if (this.es) this._attach(kind);
    return () => {
      const s = this.listeners.get(kind);
      if (!s) return;
      s.delete(fn);
      if (s.size === 0) {
        this.listeners.delete(kind);
        // We could remove the EventSource listener here, but the cost
        // is minimal — a fan-out call into an empty Set is O(1) — and
        // tracking the bound handler reference adds complexity. Leave it.
      }
    };
  }

  /** Close the EventSource; subscribers are kept (re-fired on reconnect). */
  disconnect(): void {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }

  private _attach(kind: string): void {
    if (!this.es) return;
    // Track which kinds we've already wired so we don't double-listen.
    const wired: Set<string> = (this.es as unknown as { __wired?: Set<string> }).__wired || new Set();
    if (wired.has(kind)) return;
    wired.add(kind);
    (this.es as unknown as { __wired?: Set<string> }).__wired = wired;
    this.es.addEventListener(kind, (rawEvent: MessageEvent) => {
      let payload: SseEventPayload | null = null;
      try {
        payload = JSON.parse(rawEvent.data);
      } catch (err) {
        console.warn('[sseBus] bad SSE frame, ignoring:', err);
        return;
      }
      if (!payload) return;
      const set = this.listeners.get(kind);
      if (!set) return;
      for (const fn of set) {
        try {
          fn(payload);
        } catch (err) {
          console.error('[sseBus] listener threw:', err);
        }
      }
    });
  }
}

export const sseBus = new SseBus();
