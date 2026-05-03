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

export interface CostByAgent {
  agent_id: string;
  today_usd: number;
  week_usd: number;
  lifetime_usd: number;
  lifetime_messages: number;
}

export interface CostSummary {
  today_usd: number;
  week_usd: number;
  lifetime_usd: number;
  today_input_tokens: number;
  today_output_tokens: number;
  lifetime_input_tokens: number;
  lifetime_output_tokens: number;
  top_today: CostByAgent[];
  by_agent: CostByAgent[];
  pricing: {
    input_per_million: number;
    output_per_million: number;
    cache_read_per_million: number;
    cache_write_per_million: number;
    note: string;
  };
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
