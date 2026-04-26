/**
 * Tiny fetch wrapper. All paths are /api/*; Vite proxies to backend on :3000
 * during dev, served directly when built and mounted under FastAPI.
 */
import type {
  Agent,
  AgentMessage,
  BoardColumn,
  BriefSummary,
  CostSummary,
  Ticket,
  TmuxCapture,
  TmuxWindow,
  Workspace,
} from './types';

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} on ${path}`);
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

export async function listAgents() {
  return get<Agent[]>('/api/agents');
}

export async function getAgent(id: string) {
  return get<Agent>(`/api/agents/${encodeURIComponent(id)}`);
}

export async function getAgentTickets(id: string) {
  return get<{ tickets: Ticket[]; total: number }>(
    `/api/agents/${encodeURIComponent(id)}/tickets`
  );
}

export async function getAgentInbox(id: string) {
  return get<{ messages: AgentMessage[]; total: number }>(
    `/api/agents/${encodeURIComponent(id)}/inbox`
  );
}

export async function getAgentSent(id: string) {
  return get<{ messages: AgentMessage[]; total: number }>(
    `/api/agents/${encodeURIComponent(id)}/sent`
  );
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

export async function listTmuxWindows(session: string) {
  return get<{ session: string; windows: TmuxWindow[]; exists: boolean }>(
    `/api/tmux/${encodeURIComponent(session)}/windows`
  );
}

export async function captureTmux(session: string, window: string, lines = 50) {
  return get<TmuxCapture>(
    `/api/tmux/${encodeURIComponent(session)}/${encodeURIComponent(window)}/capture?lines=${lines}`
  );
}
