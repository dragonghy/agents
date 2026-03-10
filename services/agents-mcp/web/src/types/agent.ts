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
  dispatchable: boolean;
  tmux_status: 'idle' | 'busy' | 'no_window' | 'unknown';
  workload: AgentWorkload;
  profile?: AgentProfile;
}
