export interface Ticket {
  id: number;
  headline: string;
  status: number;
  tags: string;
  priority: string;
  date: string;
  type: string;
  projectId: number;
  assignee: string | null;
  description?: string;
  userId?: number;
  storypoints?: number;
  sprint?: number;
  acceptanceCriteria?: string;
}

export interface TicketComment {
  id: number;
  text: string;
  userId: number;
  date: string;
  moduleId: number;
}

export interface Subtask {
  id: number;
  headline: string;
  status: number | string;
  tags?: string;
  priority?: string;
  assignedTo?: string;
}

export interface TicketListResponse {
  tickets: Ticket[];
  total: number;
  offset: number;
  limit: number;
}
