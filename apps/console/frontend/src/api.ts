/**
 * Tiny fetch wrapper. All paths are /api/*; Vite proxies to backend on :3000
 * during dev, served directly when built and mounted under FastAPI.
 *
 * Orchestration v1 endpoints (``/api/v1/orchestration/*``) live on the
 * daemon at :8765 and are proxied separately — see ``vite.config.ts``.
 */
import type {
  AppendMessageResult,
  BoardColumn,
  BriefSummary,
  CostSummary,
  Profile,
  Session,
  SpawnSessionBody,
  Ticket,
  Workspace,
} from './types';

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} on ${path}`);
  }
  return (await r.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = '';
    try {
      const err = await r.json();
      detail = err.error || err.detail || '';
    } catch {
      // ignore
    }
    throw new Error(`${r.status} ${r.statusText} on ${path}${detail ? `: ${detail}` : ''}`);
  }
  return (await r.json()) as T;
}

export async function getHealth() {
  return get<{ status: string; mcp_db_exists: boolean; tasks_db_exists: boolean }>(
    '/api/health'
  );
}

export async function listWorkspaces() {
  return get<{ workspaces: Workspace[]; total: number }>('/api/workspaces');
}

export async function getTicketBoard(workspaceId: number | null) {
  const qs = workspaceId !== null ? `?workspace_id=${workspaceId}` : '';
  return get<{ columns: BoardColumn[] }>(`/api/tickets/board${qs}`);
}

export async function getTicket(id: number) {
  return get<Ticket>(`/api/tickets/${id}`);
}

export async function listBriefs() {
  return get<{ briefs: BriefSummary[]; total: number }>('/api/briefs?limit=14');
}

export async function getBrief(date: string) {
  return get<{ date: string; markdown: string }>(`/api/briefs/${date}`);
}

export async function getCostSummary() {
  return get<CostSummary>('/api/cost/summary');
}

// ── Orchestration v1 (test harness, Task #17) ──

export async function listProfiles() {
  return get<{ profiles: Profile[]; total: number }>('/api/v1/orchestration/profiles');
}

export async function spawnSession(body: SpawnSessionBody) {
  return post<Session>('/api/v1/orchestration/sessions', body);
}

export async function appendMessage(sessionId: string, text: string) {
  return post<AppendMessageResult>(
    `/api/v1/orchestration/sessions/${encodeURIComponent(sessionId)}/messages`,
    { text }
  );
}

export async function closeSession(sessionId: string) {
  return post<{ ok: boolean }>(
    `/api/v1/orchestration/sessions/${encodeURIComponent(sessionId)}/close`,
    {}
  );
}

export async function getSession(sessionId: string) {
  return get<Session>(`/api/v1/orchestration/sessions/${encodeURIComponent(sessionId)}`);
}
