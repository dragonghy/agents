import { useEffect, useState, type JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchOnboardingTemplates,
  submitOnboardingSetup,
  type TeamTemplate,
  type RoleInfo,
  type AgentTemplate,
} from '../api/onboarding';

// ── Step indicator ──

function StepIndicator({ current, steps }: { current: number; steps: string[] }) {
  return (
    <div className="flex items-center justify-center mb-8">
      {steps.map((label, i) => (
        <div key={i} className="flex items-center">
          <div className="flex flex-col items-center">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                i < current
                  ? 'bg-green-500 text-white'
                  : i === current
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              }`}
            >
              {i < current ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                i + 1
              )}
            </div>
            <span
              className={`mt-1 text-xs ${
                i === current
                  ? 'text-blue-600 dark:text-blue-400 font-medium'
                  : 'text-gray-400 dark:text-gray-500'
              }`}
            >
              {label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div
              className={`w-16 h-0.5 mx-2 mb-5 ${
                i < current ? 'bg-green-500' : 'bg-gray-200 dark:bg-gray-700'
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Role icon ──

function RoleIcon({ role, className = 'w-5 h-5' }: { role: string; className?: string }) {
  const icons: Record<string, JSX.Element> = {
    admin: (
      <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
      </svg>
    ),
    dev: (
      <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
      </svg>
    ),
    qa: (
      <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    product: (
      <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15a2.25 2.25 0 012.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
      </svg>
    ),
    user: (
      <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
      </svg>
    ),
  };
  return icons[role] || icons.dev;
}

// ── Step 1: Workspace ──

function StepWorkspace({
  workspaceDir,
  onChange,
}: {
  workspaceDir: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-2">
          Workspace Directory
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          This is where your agents will work on projects. Each project will be a
          subdirectory under this path.
        </p>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Workspace path
        </label>
        <input
          type="text"
          value={workspaceDir}
          onChange={(e) => onChange(e.target.value)}
          placeholder="~/workspace"
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        />
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          Use an absolute path or ~ for home directory. Example: ~/workspace
        </p>
      </div>
    </div>
  );
}

// ── Step 2: Agent Configuration ──

function StepAgents({
  agents,
  setAgents,
  templates,
  roles,
}: {
  agents: AgentTemplate[];
  setAgents: (agents: AgentTemplate[]) => void;
  templates: TeamTemplate[];
  roles: Record<string, RoleInfo>;
}) {
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);

  function applyTemplate(templateId: string) {
    const tmpl = templates.find((t) => t.id === templateId);
    if (tmpl) {
      setAgents([...tmpl.agents]);
      setSelectedTemplate(templateId);
    }
  }

  function addAgent() {
    setSelectedTemplate(null);
    const existingDevs = agents.filter((a) => a.role === 'dev').length;
    const name = `dev-agent${existingDevs + 1}`;
    setAgents([...agents, { name, role: 'dev', template: 'dev', description: 'Developer' }]);
  }

  function removeAgent(index: number) {
    setSelectedTemplate(null);
    setAgents(agents.filter((_, i) => i !== index));
  }

  function updateAgent(index: number, field: keyof AgentTemplate, value: string) {
    setSelectedTemplate(null);
    const updated = [...agents];
    updated[index] = { ...updated[index], [field]: value };
    // Auto-set template when role changes
    if (field === 'role') {
      updated[index].template = value;
      const roleInfo = roles[value];
      if (roleInfo) {
        updated[index].description = roleInfo.description;
      }
    }
    setAgents(updated);
  }

  const nameError = (name: string, index: number): string | null => {
    if (!name) return 'Name is required';
    if (!/^[a-z][a-z0-9-]*$/.test(name)) return 'Lowercase letters, numbers, hyphens only';
    if (agents.findIndex((a, i) => i !== index && a.name === name) >= 0) return 'Duplicate name';
    return null;
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-2">
          Configure Your Team
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Choose a preset template or customize your agent team. Each agent runs
          independently and can collaborate through tickets and messages.
        </p>
      </div>

      {/* Template selector */}
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Quick Start Templates
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {templates.map((tmpl) => (
            <button
              key={tmpl.id}
              onClick={() => applyTemplate(tmpl.id)}
              className={`p-3 rounded-lg border text-left transition-colors ${
                selectedTemplate === tmpl.id
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 dark:border-blue-400'
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
              }`}
            >
              <div className="font-medium text-sm text-gray-900 dark:text-gray-100">
                {tmpl.name}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {tmpl.description}
              </div>
              <div className="text-xs text-blue-600 dark:text-blue-400 mt-2">
                {tmpl.agents.length} agent{tmpl.agents.length > 1 ? 's' : ''}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Agent list */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Agents ({agents.length})
          </label>
          <button
            onClick={addAgent}
            className="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300"
          >
            + Add Agent
          </button>
        </div>
        <div className="space-y-3">
          {agents.map((agent, i) => {
            const error = nameError(agent.name, i);
            return (
              <div
                key={i}
                className="flex items-start gap-3 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700"
              >
                <div className="mt-2 text-gray-400 dark:text-gray-500">
                  <RoleIcon role={agent.role} />
                </div>
                <div className="flex-1 grid grid-cols-1 sm:grid-cols-3 gap-2">
                  <div>
                    <input
                      type="text"
                      value={agent.name}
                      onChange={(e) => updateAgent(i, 'name', e.target.value)}
                      placeholder="agent-name"
                      className={`w-full px-2 py-1.5 text-sm border rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 ${
                        error
                          ? 'border-red-300 dark:border-red-600'
                          : 'border-gray-300 dark:border-gray-600'
                      }`}
                    />
                    {error && (
                      <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">{error}</p>
                    )}
                  </div>
                  <select
                    value={agent.role}
                    onChange={(e) => updateAgent(i, 'role', e.target.value)}
                    className="w-full px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                  >
                    {Object.entries(roles).map(([key, info]) => (
                      <option key={key} value={key}>
                        {info.label}
                      </option>
                    ))}
                  </select>
                  <div className="flex items-center">
                    <span className="flex-1 text-xs text-gray-500 dark:text-gray-400 truncate">
                      {roles[agent.role]?.description || agent.description}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => removeAgent(i)}
                  disabled={agents.length <= 1}
                  className="mt-1.5 text-gray-400 hover:text-red-500 dark:hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed"
                  title="Remove agent"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Step 3: Confirm ──

function StepConfirm({
  workspaceDir,
  agents,
  roles,
}: {
  workspaceDir: string;
  agents: AgentTemplate[];
  roles: Record<string, RoleInfo>;
}) {
  const roleCounts: Record<string, number> = {};
  for (const a of agents) {
    roleCounts[a.role] = (roleCounts[a.role] || 0) + 1;
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-2">
          Review Configuration
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Please review your setup before generating the configuration file.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Workspace</h4>
          <p className="text-sm text-gray-900 dark:text-gray-100 font-mono">{workspaceDir}</p>
        </div>
        <div className="p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
          <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Team Size</h4>
          <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {agents.length}
            <span className="text-sm font-normal text-gray-500 dark:text-gray-400 ml-1">
              agent{agents.length > 1 ? 's' : ''}
            </span>
          </p>
          <div className="flex gap-2 mt-1 flex-wrap">
            {Object.entries(roleCounts).map(([role, count]) => (
              <span
                key={role}
                className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded"
              >
                {count} {roles[role]?.label || role}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Agent list */}
      <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-700 dark:text-gray-300">Name</th>
              <th className="px-4 py-2 text-left font-medium text-gray-700 dark:text-gray-300">Role</th>
              <th className="px-4 py-2 text-left font-medium text-gray-700 dark:text-gray-300">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {agents.map((agent, i) => (
              <tr key={i} className="bg-white dark:bg-gray-900">
                <td className="px-4 py-2 font-mono text-gray-900 dark:text-gray-100">{agent.name}</td>
                <td className="px-4 py-2">
                  <span className="inline-flex items-center gap-1.5">
                    <RoleIcon role={agent.role} className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <span className="text-gray-700 dark:text-gray-300">{roles[agent.role]?.label || agent.role}</span>
                  </span>
                </td>
                <td className="px-4 py-2 text-gray-500 dark:text-gray-400">{roles[agent.role]?.description || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* What happens next */}
      <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
        <h4 className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-2">What happens next?</h4>
        <ol className="text-sm text-blue-700 dark:text-blue-400 space-y-1 list-decimal list-inside">
          <li>An <code className="text-xs bg-blue-100 dark:bg-blue-900/50 px-1 rounded">agents.yaml</code> configuration file will be generated</li>
          <li>Run <code className="text-xs bg-blue-100 dark:bg-blue-900/50 px-1 rounded">python3 setup-agents.py</code> to scaffold agent workspaces</li>
          <li>Run <code className="text-xs bg-blue-100 dark:bg-blue-900/50 px-1 rounded">bash restart_all_agents.sh</code> to start all agents</li>
        </ol>
      </div>
    </div>
  );
}

// ── Success screen ──

function SetupComplete({
  agentsCount,
  nextSteps,
}: {
  agentsCount: number;
  nextSteps: string[];
}) {
  const navigate = useNavigate();

  return (
    <div className="max-w-lg mx-auto text-center py-8">
      <div className="w-16 h-16 mx-auto mb-4 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center">
        <svg className="w-8 h-8 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-2">Setup Complete!</h2>
      <p className="text-gray-500 dark:text-gray-400 mb-6">
        Your team of {agentsCount} agent{agentsCount > 1 ? 's' : ''} has been configured.
      </p>

      <div className="text-left bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4 mb-6 border border-gray-200 dark:border-gray-700">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Next Steps</h4>
        <ol className="text-sm text-gray-600 dark:text-gray-400 space-y-2 list-decimal list-inside">
          {nextSteps.map((step, i) => (
            <li key={i}>
              <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded font-mono">
                {step}
              </code>
            </li>
          ))}
        </ol>
      </div>

      <button
        onClick={() => navigate('/')}
        className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
      >
        Go to Dashboard
      </button>
    </div>
  );
}

// ── Main Onboarding Component ──

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [workspaceDir, setWorkspaceDir] = useState('~/workspace');
  const [agents, setAgents] = useState<AgentTemplate[]>([]);
  const [templates, setTemplates] = useState<TeamTemplate[]>([]);
  const [roles, setRoles] = useState<Record<string, RoleInfo>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupResult, setSetupResult] = useState<{ agentsCount: number; nextSteps: string[] } | null>(null);

  // Load templates on mount
  useEffect(() => {
    async function load() {
      try {
        const data = await fetchOnboardingTemplates();
        setTemplates(data.templates);
        setRoles(data.roles);
        // Default to standard template
        const standard = data.templates.find((t) => t.id === 'standard');
        if (standard) {
          setAgents([...standard.agents]);
        } else if (data.templates.length > 0) {
          setAgents([...data.templates[0].agents]);
        }
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const steps = ['Workspace', 'Team', 'Confirm'];

  function canProceed(): boolean {
    if (step === 0) {
      return workspaceDir.trim().length > 0;
    }
    if (step === 1) {
      if (agents.length === 0) return false;
      const nameRe = /^[a-z][a-z0-9-]*$/;
      const names = new Set<string>();
      for (const a of agents) {
        if (!a.name || !nameRe.test(a.name)) return false;
        if (names.has(a.name)) return false;
        names.add(a.name);
      }
      return true;
    }
    return true;
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitOnboardingSetup({
        workspace_dir: workspaceDir,
        agents: agents.map((a) => ({
          name: a.name,
          role: a.role,
          template: a.template || a.role,
        })),
      });
      setSetupResult({
        agentsCount: result.agents_count,
        nextSteps: result.next_steps,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  // Show success screen
  if (setupResult) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center p-4">
        <div className="w-full max-w-2xl">
          <SetupComplete agentsCount={setupResult.agentsCount} nextSteps={setupResult.nextSteps} />
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center">
        <div className="text-gray-500 dark:text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-800 dark:text-gray-100 mb-2">
            Welcome to Agent-Hub
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            Let's set up your AI agent team in a few steps.
          </p>
        </div>

        {/* Progress */}
        <StepIndicator current={step} steps={steps} />

        {/* Step content */}
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 shadow-sm">
          {step === 0 && (
            <StepWorkspace workspaceDir={workspaceDir} onChange={setWorkspaceDir} />
          )}
          {step === 1 && (
            <StepAgents
              agents={agents}
              setAgents={setAgents}
              templates={templates}
              roles={roles}
            />
          )}
          {step === 2 && (
            <StepConfirm workspaceDir={workspaceDir} agents={agents} roles={roles} />
          )}

          {/* Error */}
          {error && (
            <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          {/* Navigation */}
          <div className="mt-6 flex justify-between">
            <button
              onClick={() => setStep(step - 1)}
              disabled={step === 0}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Back
            </button>
            {step < steps.length - 1 ? (
              <button
                onClick={() => setStep(step + 1)}
                disabled={!canProceed()}
                className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            ) : (
              <button
                onClick={handleSubmit}
                disabled={submitting || !canProceed()}
                className="px-6 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? 'Setting up...' : 'Generate Configuration'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
