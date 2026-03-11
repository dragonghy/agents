import type { Agent, AgentUsage, AgentUsageSummary } from '../types/agent';

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

export async function fetchAgentUsage(id: string): Promise<AgentUsage> {
  const res = await fetch(`/api/v1/agents/${id}/usage`);
  if (!res.ok) throw new Error(`Failed to fetch usage for ${id}: ${res.status}`);
  return res.json();
}

export async function refreshAgentUsage(id: string): Promise<AgentUsage> {
  const res = await fetch(`/api/v1/agents/${id}/usage/refresh`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to refresh usage for ${id}: ${res.status}`);
  return res.json();
}

export async function fetchAllUsage(): Promise<AgentUsageSummary[]> {
  const res = await fetch('/api/v1/usage');
  if (!res.ok) throw new Error(`Failed to fetch usage: ${res.status}`);
  return res.json();
}
