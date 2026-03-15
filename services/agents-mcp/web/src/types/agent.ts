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

export interface TokenTotals {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  message_count: number;
}

export interface DailyTotal extends TokenTotals {
  date: string;
}

export interface AgentUsage {
  today: TokenTotals;
  lifetime: TokenTotals;
  by_model: Record<string, TokenTotals>;
  daily_totals: DailyTotal[];
}

export interface AgentUsageSummary {
  agent_id: string;
  project?: string;
  work_stream?: string;
  lifetime: TokenTotals;
  today: TokenTotals;
}

export interface Agent {
  id: string;
  role: string;
  description: string;
  project?: string;
  work_stream?: string;
  dispatchable: boolean;
  tmux_status: 'idle' | 'busy' | 'rate_limited' | 'no_window' | 'unknown';
  workload: AgentWorkload;
  profile?: AgentProfile;
}
