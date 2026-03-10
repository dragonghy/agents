import type { Agent } from '../types/agent';

export async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch('/api/v1/agents');
  if (!res.ok) throw new Error(`Failed to fetch agents: ${res.status}`);
  return res.json();
}

export async function fetchAgent(id: string): Promise<Agent> {
  const res = await fetch(`/api/v1/agents/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch agent ${id}: ${res.status}`);
  return res.json();
}

export async function fetchAgentTerminal(id: string, raw = false): Promise<{ agent_id: string; output: string; raw?: boolean; error?: string }> {
  const res = await fetch(`/api/v1/agents/${id}/terminal?raw=${raw}`);
  if (!res.ok) throw new Error(`Failed to fetch terminal for ${id}: ${res.status}`);
  return res.json();
}
