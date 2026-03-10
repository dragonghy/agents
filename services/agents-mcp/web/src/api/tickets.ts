import type { Ticket, TicketListResponse, TicketComment, Subtask } from '../types/ticket';

export async function fetchTickets(params?: Record<string, string>): Promise<TicketListResponse> {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(`/api/v1/tickets${query}`);
  if (!res.ok) throw new Error(`Failed to fetch tickets: ${res.status}`);
  return res.json();
}

export async function fetchTicket(id: number): Promise<Ticket> {
  const res = await fetch(`/api/v1/tickets/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch ticket ${id}: ${res.status}`);
  return res.json();
}

export async function fetchTicketComments(id: number): Promise<TicketComment[]> {
  const res = await fetch(`/api/v1/tickets/${id}/comments`);
  if (!res.ok) throw new Error(`Failed to fetch comments: ${res.status}`);
  return res.json();
}

export async function fetchTicketSubtasks(id: number): Promise<Subtask[]> {
  const res = await fetch(`/api/v1/tickets/${id}/subtasks`);
  if (!res.ok) throw new Error(`Failed to fetch subtasks: ${res.status}`);
  return res.json();
}

export async function fetchStatusLabels(): Promise<Record<string, string>> {
  const res = await fetch('/api/v1/status-labels');
  if (!res.ok) throw new Error(`Failed to fetch status labels: ${res.status}`);
  return res.json();
}
