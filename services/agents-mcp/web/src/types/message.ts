export interface Message {
  id: number;
  from_agent: string;
  to_agent: string;
  body: string;
  is_read: number;
  created_at: string;
}

export interface ConversationThread {
  agent_a: string;
  agent_b: string;
  last_message_at: string;
  message_count: number;
  last_message: string;
  last_sender: string;
}

export interface MessagesResponse {
  messages: Message[];
  total: number;
  threads: ConversationThread[];
}
