export interface Workspace {
  id: number;
  name: string;
  kind: string;
  description: string;
  default_assignee: string;
  created_at: string;
  updated_at: string;
}

export interface AgentWorkload {
  in_progress: number;
  new: number;
  blocked: number;
  total_active: number;
}

export interface AgentProfile {
  identity: string | null;
  current_context: string | null;
  expertise: string | null;
  updated_at: string | null;
}

export interface Agent {
  id: string;
  role: string;
  description: string;
  project: string;
  work_stream: string;
  dispatchable: boolean;
  agent_type: string;
  tmux_status: 'active' | 'idle' | 'no_window' | 'unavailable';
  workload: AgentWorkload;
  profile?: AgentProfile;
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

export interface TmuxWindow {
  name: string;
  active: boolean;
}

export interface TmuxCapture {
  session: string;
  window: string;
  lines_requested: number;
  raw: boolean;
  output: string;
}

export interface AgentMessage {
  id: number;
  from_agent: string;
  to_agent: string;
  body: string;
  created_at: string;
  read_at: string | null;
}
