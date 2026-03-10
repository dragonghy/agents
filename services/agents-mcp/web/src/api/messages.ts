import type { MessagesResponse, Message } from '../types/message';

export async function fetchMessages(params?: Record<string, string>): Promise<MessagesResponse> {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(`/api/v1/messages${query}`);
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.status}`);
  return res.json();
}

export async function fetchConversation(
  agentA: string,
  agentB: string,
  params?: Record<string, string>,
): Promise<Message[]> {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  const res = await fetch(`/api/v1/messages/conversation/${agentA}/${agentB}${query}`);
  if (!res.ok) throw new Error(`Failed to fetch conversation: ${res.status}`);
  return res.json();
}
