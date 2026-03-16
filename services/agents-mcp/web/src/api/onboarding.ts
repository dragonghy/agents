export interface OnboardingStatus {
  completed: boolean;
}

export interface AgentTemplate {
  name: string;
  role: string;
  template?: string;
  description: string;
}

export interface TeamTemplate {
  id: string;
  name: string;
  description: string;
  agents: AgentTemplate[];
}

export interface RoleInfo {
  label: string;
  description: string;
  icon: string;
}

export interface TemplatesResponse {
  templates: TeamTemplate[];
  roles: Record<string, RoleInfo>;
  available_roles: string[];
}

export interface SetupRequest {
  workspace_dir: string;
  agents: Array<{
    name: string;
    role: string;
    template?: string;
  }>;
}

export interface SetupResponse {
  status: string;
  config_path: string;
  agents_count: number;
  next_steps: string[];
  error?: string;
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await fetch('/api/v1/onboarding/status');
  if (!res.ok) throw new Error(`Failed to fetch onboarding status: ${res.status}`);
  return res.json();
}

export async function fetchOnboardingTemplates(): Promise<TemplatesResponse> {
  const res = await fetch('/api/v1/onboarding/templates');
  if (!res.ok) throw new Error(`Failed to fetch templates: ${res.status}`);
  return res.json();
}

export async function submitOnboardingSetup(data: SetupRequest): Promise<SetupResponse> {
  const res = await fetch('/api/v1/onboarding/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw new Error(err.error || `Setup failed: ${res.status}`);
  }
  return res.json();
}
