export interface Workspace {
  id: number;
  name: string;
  kind: string;
  description: string;
  default_assignee: string;
  created_at: string;
  updated_at: string;
}

export interface Ticket {
  id: number;
  headline: string;
  type: string;
  status: number;
  priority: string;
  tags: string;
  projectId?: number;
  assignee: string;
  workspace_id: number;
  phase: string;
  depends_on?: string;
  date: string;
}

export interface BoardColumn {
  status: number;
  label: string;
  tickets: Ticket[];
}

export interface BriefSummary {
  date: string;
  filename: string;
  size_bytes: number;
}

// ── Orchestration v1 (Phase 1+2 test harness, Task #17) ──

export interface Profile {
  name: string;
  description: string;
  runner_type: string;
  file_path: string;
  file_hash: string;
  loaded_at: string | null;
  last_used_at: string | null;
}

export interface Session {
  id: string;
  profile_name: string;
  binding_kind: 'ticket-subagent' | 'human-channel' | 'standalone';
  ticket_id: number | null;
  channel_id: string | null;
  parent_session_id: string | null;
  status: 'active' | 'closed';
  runner_type: string;
  native_handle: string | null;
  cost_tokens_in: number;
  cost_tokens_out: number;
  created_at?: string;
  closed_at?: string | null;
}

export interface SpawnSessionBody {
  profile_name: string;
  binding_kind: 'ticket-subagent' | 'human-channel' | 'standalone';
  ticket_id?: number;
  channel_id?: string;
  parent_session_id?: string;
}

export interface AppendMessageResult {
  assistant_text: string;
  tokens_in: number;
  tokens_out: number;
  native_handle: string;
}

export interface SessionMessage {
  role: 'user' | 'assistant';
  text: string;
  ts: number; // local epoch ms — for stable React keys
}

// ── Cost dashboard (Task #18 Part A) ──

export interface CostBySessionRow {
  id: string;
  profile_name: string;
  ticket_id: number | null;
  channel_id: string | null;
  status: 'active' | 'closed';
  cost_tokens_in: number;
  cost_tokens_out: number;
  cost_usd: number;
  created_at: string;
}

export interface CostByProfileRow {
  profile_name: string;
  sessions_count: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_usd: number;
  last_used_at: string | null;
}

export interface CostByTicketRow {
  ticket_id: number;
  sessions_count: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_usd: number;
  last_used_at: string | null;
}

export interface CostBucket {
  tokens_in: number;
  tokens_out: number;
  sessions_count: number;
  usd: number;
}

export interface CostTotalsResponse {
  today: CostBucket;
  week: CostBucket;
  lifetime: CostBucket;
  pricing: {
    input_per_million: number;
    output_per_million: number;
    note: string;
  };
}

// ── Sessions list + history (Task #18 Part B) ──

export interface RenderedHistoryMessage {
  role: 'user' | 'assistant';
  text: string;
  timestamp: string;
}

export interface SessionHistoryResponse {
  messages: RenderedHistoryMessage[];
  total: number;
}

export interface ListSessionsResponse {
  sessions: Session[];
  total: number;
  limit: number;
  offset: number;
}

// ── Profile detail (Task #18 Part C) ──

export interface ProfileBody {
  name: string;
  description: string;
  runner_type: string;
  system_prompt: string;
  mcp_servers: string[];
  skills: string[];
  orchestration_tools: boolean;
  file_path: string;
  file_hash: string;
}

export interface ProfileDetailResponse {
  registry: Profile;
  profile: ProfileBody | null;
  error?: string;
}

export interface ProfileSessionsResponse {
  sessions: Session[];
  total: number;
  profile_name: string;
}

// ── Ticket detail + tree (Task #20 — UI rework) ──

export interface TicketSummary {
  id: number;
  headline: string;
  status: number;
  priority: string;
  type: string;
  tags: string;
  assignee: string;
  workspace_id?: number | null;
  workspace_name?: string | null;
  projectId?: number | null;
  phase?: string;
  date?: string;
  dependencies?: { depends_on_count: number; dependents_count: number };
}

export interface TicketDependencyRef {
  id: number;
  headline: string | null;
  status: number | null;
}

export interface TicketDetail extends Omit<TicketSummary, 'dependencies'> {
  description?: string | null;
  project_name?: string | null;
  dependencies: {
    depends_on: TicketDependencyRef[];
    dependents: TicketDependencyRef[];
  };
}

export interface TicketComment {
  id: number;
  text: string;
  author: string | null;
  date: string;
  userId?: number | null;
  moduleId?: number;
}

export interface TicketCommentsResponse {
  comments: TicketComment[];
  total: number;
  limit?: number;
  offset?: number;
}

export interface TicketSessionsResponse {
  sessions: Session[];
  total: number;
  ticket_id: number;
  limit?: number;
  offset?: number;
}

export interface TicketTreeTicket {
  ticket: TicketSummary;
  children: TicketSummary[];
}

export interface TicketTreeProject {
  project: { id: number | null; name: string | null };
  tickets: TicketTreeTicket[];
}

export interface TicketTreeWorkspace {
  workspace: { id: number | null; name: string; kind: string | null };
  projects: TicketTreeProject[];
}

export interface TicketTreeResponse {
  workspaces: TicketTreeWorkspace[];
}

export interface ListTicketsResponse {
  tickets: TicketSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface PatchTicketBody {
  status?: number;
  priority?: string;
  headline?: string;
}
