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
  CostBySessionRow,
  CostByProfileRow,
  CostByTicketRow,
  CostTotalsResponse,
  ListSessionsResponse,
  ListTicketsResponse,
  PatchTicketBody,
  Profile,
  ProfileDetailResponse,
  ProfileSessionsResponse,
  Session,
  SessionHistoryResponse,
  SpawnSessionBody,
  Ticket,
  TicketCommentsResponse,
  TicketDetail,
  TicketSessionsResponse,
  TicketTreeResponse,
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

async function patch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'PATCH',
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

// ── Cost (Task #18 Part A) ──

export async function getCostBySession(opts: {
  limit?: number;
  offset?: number;
  status?: string;
  profile?: string;
  ticket?: number;
}) {
  const qp = new URLSearchParams();
  if (opts.limit !== undefined) qp.set('limit', String(opts.limit));
  if (opts.offset !== undefined) qp.set('offset', String(opts.offset));
  if (opts.status) qp.set('status', opts.status);
  if (opts.profile) qp.set('profile', opts.profile);
  if (opts.ticket !== undefined) qp.set('ticket', String(opts.ticket));
  const qs = qp.toString() ? `?${qp.toString()}` : '';
  return get<{
    sessions: CostBySessionRow[];
    total: number;
    limit: number;
    offset: number;
  }>(`/api/v1/orchestration/cost/by-session${qs}`);
}

export async function getCostByProfile() {
  return get<{ rollup: CostByProfileRow[]; total: number }>(
    '/api/v1/orchestration/cost/by-profile'
  );
}

export async function getCostByTicket() {
  return get<{ rollup: CostByTicketRow[]; total: number }>(
    '/api/v1/orchestration/cost/by-ticket'
  );
}

export async function getCostTotals() {
  return get<CostTotalsResponse>('/api/v1/orchestration/cost/totals');
}

export interface CostByDayRow {
  date: string;
  tokens_in: number;
  tokens_out: number;
  sessions_count: number;
  usd: number;
}

export async function getCostByDay(days = 30) {
  return get<{ days: CostByDayRow[]; total: number; window_days: number }>(
    `/api/v1/orchestration/cost/by-day?days=${days}`,
  );
}

export interface SystemInfo {
  pid: number;
  started_at: number;
  uptime_seconds: number;
  profiles_loaded: number | null;
  profiles: Array<{ name: string; runner_type: string; last_used_at: string | null }>;
  sessions_lifetime: number | null;
  db_size_bytes: number | null;
  mcp_servers: Array<{ name: string; scope: 'global' | 'personal'; command: string | null }>;
  telegram: { allowed_chat_ids: string[]; primary_chat_id: string | null };
}

export async function getSystemInfo() {
  return get<SystemInfo>('/api/v1/orchestration/system');
}

// ── Session list + history (Task #18 Part B) ──

export async function listSessions(opts: {
  limit?: number;
  offset?: number;
  status?: string;
  profile?: string;
  ticket?: number;
}) {
  const qp = new URLSearchParams();
  if (opts.limit !== undefined) qp.set('limit', String(opts.limit));
  if (opts.offset !== undefined) qp.set('offset', String(opts.offset));
  if (opts.status) qp.set('status', opts.status);
  if (opts.profile) qp.set('profile', opts.profile);
  if (opts.ticket !== undefined) qp.set('ticket', String(opts.ticket));
  const qs = qp.toString() ? `?${qp.toString()}` : '';
  return get<ListSessionsResponse>(`/api/v1/orchestration/sessions${qs}`);
}

export async function getSessionHistory(sessionId: string) {
  return get<SessionHistoryResponse>(
    `/api/v1/orchestration/sessions/${encodeURIComponent(sessionId)}/history`
  );
}

// ── Profile detail (Task #18 Part C) ──

export async function getProfile(name: string) {
  return get<ProfileDetailResponse>(
    `/api/v1/orchestration/profiles/${encodeURIComponent(name)}`
  );
}

export async function getProfileSessions(name: string, limit = 10) {
  return get<ProfileSessionsResponse>(
    `/api/v1/orchestration/profiles/${encodeURIComponent(name)}/sessions?limit=${limit}`
  );
}

// ── Ticket detail + tree (Task #20) ──

export async function listTickets(opts: {
  workspace?: number | null;
  project?: number | null;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const qp = new URLSearchParams();
  if (opts.workspace != null) qp.set('workspace', String(opts.workspace));
  if (opts.project != null) qp.set('project', String(opts.project));
  if (opts.status) qp.set('status', opts.status);
  if (opts.limit !== undefined) qp.set('limit', String(opts.limit));
  if (opts.offset !== undefined) qp.set('offset', String(opts.offset));
  const qs = qp.toString() ? `?${qp.toString()}` : '';
  return get<ListTicketsResponse>(`/api/v1/orchestration/tickets${qs}`);
}

export async function getTicketTree(workspace?: number | null) {
  const qs = workspace != null ? `?workspace=${workspace}` : '';
  return get<TicketTreeResponse>(`/api/v1/orchestration/tickets/tree${qs}`);
}

export async function getTicketDetail(id: number) {
  return get<TicketDetail>(`/api/v1/orchestration/tickets/${id}`);
}

export async function getTicketComments(id: number) {
  return get<TicketCommentsResponse>(`/api/v1/orchestration/tickets/${id}/comments`);
}

export async function getTicketSessions(id: number) {
  return get<TicketSessionsResponse>(`/api/v1/orchestration/tickets/${id}/sessions`);
}

export async function patchTicket(id: number, body: PatchTicketBody) {
  return patch<{ ok: boolean; ticket: TicketDetail | null }>(
    `/api/v1/orchestration/tickets/${id}`,
    body,
  );
}

export async function addTicketComment(id: number, body: string, author?: string) {
  return post<{ ok: boolean; comment_id: number }>(
    `/api/v1/orchestration/tickets/${id}/comments`,
    author ? { body, author } : { body },
  );
}

export interface CreateTicketBody {
  headline: string;
  description?: string;
  assignee?: string;
  tags?: string;
  priority?: string;
  parent_id?: number;
  workspace_id?: number;
  project_id?: number;
  type?: string;
}

export async function createTicket(body: CreateTicketBody) {
  return post<{ ok: boolean; ticket: TicketDetail }>(
    '/api/v1/orchestration/tickets',
    body,
  );
}
