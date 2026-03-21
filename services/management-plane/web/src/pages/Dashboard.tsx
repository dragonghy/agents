import { useEffect, useState, useCallback } from "react";
import {
  getDashboardStats,
  formatTokens,
  type DashboardStats,
  type AgentDetail,
  type User,
} from "../lib/api";
import Navbar from "../components/Navbar";

// ── Status styling ──

const AGENT_STATUS_CONFIG: Record<
  string,
  { dot: string; bg: string; label: string; order: number }
> = {
  error: { dot: "bg-red-500", bg: "bg-red-50 border-red-200", label: "Error", order: 0 },
  busy: { dot: "bg-yellow-500", bg: "bg-yellow-50 border-yellow-200", label: "Busy", order: 1 },
  blocked: { dot: "bg-orange-500", bg: "bg-orange-50 border-orange-200", label: "Blocked", order: 2 },
  idle: { dot: "bg-green-500", bg: "bg-green-50 border-green-200", label: "Idle", order: 3 },
};

function getAgentStatusConfig(status: string) {
  return AGENT_STATUS_CONFIG[status] || { dot: "bg-gray-400", bg: "bg-gray-50 border-gray-200", label: status, order: 99 };
}

// ── Needs Attention Bar ──

function NeedsAttentionBar({
  humanBlocked,
  staleCount,
  errorAgents,
}: {
  humanBlocked: number;
  staleCount: number;
  errorAgents: number;
}) {
  const items: string[] = [];
  if (humanBlocked > 0) items.push(`${humanBlocked} human-blocked ticket${humanBlocked > 1 ? "s" : ""}`);
  if (errorAgents > 0) items.push(`${errorAgents} agent${errorAgents > 1 ? "s" : ""} in error`);
  if (staleCount > 0) items.push(`${staleCount} stale ticket${staleCount > 1 ? "s" : ""}`);

  if (items.length === 0) return null;

  return (
    <div className="bg-amber-50 border border-amber-300 rounded-xl px-5 py-3 mb-6 flex items-center gap-3">
      <span className="text-amber-600 text-lg flex-shrink-0">&#9888;</span>
      <p className="text-sm text-amber-800 font-medium">
        Needs attention: {items.join(", ")}
      </p>
    </div>
  );
}

// ── Summary Card ──

function SummaryCard({
  title,
  value,
  items,
  accent,
}: {
  title: string;
  value: string;
  items: Array<{ label: string; count: string | number }>;
  accent: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-sm transition-shadow">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wide">{title}</h3>
      </div>
      <p className={`text-3xl font-bold ${accent} mb-3`}>{value}</p>
      <div className="space-y-1">
        {items.map((item, i) => (
          <div key={i} className="flex justify-between text-sm">
            <span className="text-gray-500">{item.label}</span>
            <span className="font-medium text-gray-700">{item.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Agent List ──

function AgentStatusList({ agents }: { agents: AgentDetail[] }) {
  const [showAllIdle, setShowAllIdle] = useState(false);

  // Sort: error > busy > blocked > idle
  const sorted = [...agents].sort((a, b) => {
    const aOrder = getAgentStatusConfig(a.status).order;
    const bOrder = getAgentStatusConfig(b.status).order;
    if (aOrder !== bOrder) return aOrder - bOrder;
    return a.name.localeCompare(b.name);
  });

  const nonIdle = sorted.filter((a) => a.status !== "idle");
  const idle = sorted.filter((a) => a.status === "idle");
  const IDLE_PREVIEW = 2;

  const visibleIdle = showAllIdle ? idle : idle.slice(0, IDLE_PREVIEW);
  const hiddenIdleCount = idle.length - IDLE_PREVIEW;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
        Agent Status
      </h3>
      {agents.length === 0 ? (
        <p className="text-gray-400 text-sm py-4 text-center">
          No agent data available. Daemon may be offline.
        </p>
      ) : (
        <div className="space-y-2">
          {nonIdle.map((agent) => {
            const cfg = getAgentStatusConfig(agent.status);
            return (
              <div
                key={agent.name}
                className={`flex items-center justify-between px-3 py-2 rounded-lg border ${cfg.bg}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
                  <span className="font-medium text-sm text-gray-900 truncate">{agent.name}</span>
                  <span className="text-xs text-gray-500">({cfg.label})</span>
                </div>
                {agent.current_ticket && (
                  <span className="text-xs text-gray-500 truncate ml-2 max-w-[50%] text-right">
                    {agent.current_ticket}
                  </span>
                )}
              </div>
            );
          })}

          {visibleIdle.map((agent) => {
            const cfg = getAgentStatusConfig("idle");
            return (
              <div
                key={agent.name}
                className={`flex items-center px-3 py-2 rounded-lg border ${cfg.bg}`}
              >
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
                <span className="font-medium text-sm text-gray-900 ml-2">{agent.name}</span>
                <span className="text-xs text-gray-500 ml-1">(Idle)</span>
              </div>
            );
          })}

          {!showAllIdle && hiddenIdleCount > 0 && (
            <button
              onClick={() => setShowAllIdle(true)}
              className="text-sm text-indigo-600 hover:text-indigo-700 px-3 py-1"
            >
              + {hiddenIdleCount} more idle agent{hiddenIdleCount > 1 ? "s" : ""}
            </button>
          )}
          {showAllIdle && idle.length > IDLE_PREVIEW && (
            <button
              onClick={() => setShowAllIdle(false)}
              className="text-sm text-indigo-600 hover:text-indigo-700 px-3 py-1"
            >
              Show less
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Token Chart (pure CSS bars) ──

function TokenChart({ daily }: { daily: Array<{ date: string; total_tokens: number }> }) {
  const maxTokens = Math.max(...daily.map((d) => d.total_tokens), 1);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
        Token Usage (7 days)
      </h3>
      {daily.length === 0 ? (
        <p className="text-gray-400 text-sm py-4 text-center">No usage data yet.</p>
      ) : (
        <div className="flex items-end gap-2 h-40">
          {daily.map((d) => {
            const pct = (d.total_tokens / maxTokens) * 100;
            const barHeight = Math.max(pct, 2); // minimum 2% so empty days show a sliver
            const dateLabel = d.date.slice(5); // "MM-DD"
            return (
              <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-xs text-gray-500 font-medium">
                  {d.total_tokens > 0 ? formatTokens(d.total_tokens) : ""}
                </span>
                <div className="w-full flex items-end" style={{ height: "120px" }}>
                  <div
                    className="w-full bg-indigo-500 rounded-t-md transition-all duration-300 hover:bg-indigo-600"
                    style={{ height: `${barHeight}%` }}
                    title={`${d.date}: ${d.total_tokens.toLocaleString()} tokens`}
                  />
                </div>
                <span className="text-xs text-gray-400">{dateLabel}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main Dashboard ──

interface Props {
  user: User;
}

export default function Dashboard({ user }: Props) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const refresh = useCallback(async () => {
    try {
      const data = await getDashboardStats();
      setStats(data);
      setError(null);
      setLastRefresh(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30_000);
    return () => clearInterval(interval);
  }, [refresh]);

  // Build summary card data
  const agentItems = stats
    ? Object.entries(stats.agents.by_status)
        .sort(([a], [b]) => (getAgentStatusConfig(a).order - getAgentStatusConfig(b).order))
        .map(([status, count]) => ({
          label: getAgentStatusConfig(status).label,
          count,
        }))
    : [];

  const ticketItems = stats
    ? Object.entries(stats.tickets.by_status)
        .filter(([s]) => s !== "done")
        .map(([status, count]) => ({ label: status.replace("_", " "), count }))
    : [];

  const tokenChange = stats && stats.tokens.yesterday > 0
    ? Math.round(((stats.tokens.today - stats.tokens.yesterday) / stats.tokens.yesterday) * 100)
    : null;

  const errorAgentCount = stats?.agents.by_status["error"] || 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar user={user} />

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
            <button
              onClick={refresh}
              disabled={loading}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              Refresh
            </button>
          </div>
        </div>

        {loading && !stats ? (
          <div className="text-center text-gray-500 py-16">Loading dashboard...</div>
        ) : error && !stats ? (
          <div className="text-center py-16">
            <p className="text-red-500 mb-4">{error}</p>
            <button
              onClick={refresh}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm"
            >
              Retry
            </button>
          </div>
        ) : stats ? (
          <>
            {/* Needs Attention */}
            <NeedsAttentionBar
              humanBlocked={stats.tickets.human_blocked}
              staleCount={stats.tickets.stale_count}
              errorAgents={errorAgentCount}
            />

            {/* 4 Summary Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <SummaryCard
                title="Agents"
                value={String(stats.agents.total)}
                items={agentItems}
                accent="text-indigo-600"
              />
              <SummaryCard
                title="Tickets"
                value={String(stats.tickets.total)}
                items={ticketItems}
                accent="text-blue-600"
              />
              <SummaryCard
                title="Tokens Today"
                value={formatTokens(stats.tokens.today)}
                items={[
                  { label: "Yesterday", count: formatTokens(stats.tokens.yesterday) },
                  ...(tokenChange !== null
                    ? [{ label: "Change", count: `${tokenChange >= 0 ? "+" : ""}${tokenChange}%` }]
                    : []),
                ]}
                accent="text-emerald-600"
              />
              <SummaryCard
                title="Messages"
                value={String(stats.messages.unread_total)}
                items={[{ label: "Unread", count: stats.messages.unread_total }]}
                accent="text-purple-600"
              />
            </div>

            {/* Agent Status + Token Chart */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <AgentStatusList agents={stats.agents.details} />
              <TokenChart daily={stats.tokens.daily} />
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
