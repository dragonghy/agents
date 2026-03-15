import { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { fetchAllUsage, fetchAgentUsage } from '../api/agents';
import type { AgentUsageSummary, AgentUsage, TokenTotals } from '../types/agent';
import { formatTokens, totalTokens } from '../utils/format';
import { useTheme } from '../hooks/useTheme';

// Color palette for agents (works on both light and dark)
const AGENT_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

type ViewMode = 'daily' | 'overall';
type DateRange = 7 | 14 | 30;

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />;
}

// ---------- metric card ----------
function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
      <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">{label}</div>
      <div className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">{value}</div>
      {sub && <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{sub}</div>}
    </div>
  );
}

// ---------- custom tooltip for bar chart ----------
function DailyTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded shadow-lg p-3 text-sm">
      <div className="font-medium text-gray-800 dark:text-gray-200 mb-1">{label}</div>
      {payload.map((entry: any) => (
        <div key={entry.dataKey} className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-gray-600 dark:text-gray-400">{entry.name}:</span>
          <span className="font-medium text-gray-800 dark:text-gray-200">{formatTokens(entry.value)}</span>
        </div>
      ))}
    </div>
  );
}

// ---------- custom tooltip for pie chart ----------
function PieTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0];
  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded shadow-lg p-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.payload.fill }} />
        <span className="font-medium text-gray-800 dark:text-gray-200">{d.name}</span>
      </div>
      <div className="text-gray-600 dark:text-gray-400 mt-1">
        {formatTokens(d.value)} ({((d.payload.percent || 0) * 100).toFixed(1)}%)
      </div>
    </div>
  );
}

// ---------- main component ----------
export default function Tokens() {
  const { theme } = useTheme();
  const isDark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);

  const [view, setView] = useState<ViewMode>('daily');
  const [dateRange, setDateRange] = useState<DateRange>(14);
  const [usageSummaries, setUsageSummaries] = useState<AgentUsageSummary[]>([]);
  const [agentUsages, setAgentUsages] = useState<Record<string, AgentUsage>>({});
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch agents + usage summaries
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const summaries = await fetchAllUsage();
        if (active) {
          setUsageSummaries(summaries);
          // Select all agents by default
          setSelectedAgents(new Set(summaries.map(s => s.agent_id)));
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 30000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  // Fetch per-agent daily data when switching to daily view
  useEffect(() => {
    if (view !== 'daily' || usageSummaries.length === 0) return;
    let active = true;

    async function loadDaily() {
      const ids = usageSummaries.map(s => s.agent_id);
      const results: Record<string, AgentUsage> = {};
      // Fetch in parallel (agents < 20, acceptable)
      const fetched = await Promise.allSettled(
        ids.map(id => fetchAgentUsage(id).then(u => ({ id, usage: u })))
      );
      for (const r of fetched) {
        if (r.status === 'fulfilled') {
          results[r.value.id] = r.value.usage;
        }
      }
      if (active) setAgentUsages(results);
    }
    loadDaily();
    return () => { active = false; };
  }, [view, usageSummaries]);

  // Derive agent color map
  const agentColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    usageSummaries.forEach((s, i) => {
      map[s.agent_id] = AGENT_COLORS[i % AGENT_COLORS.length];
    });
    return map;
  }, [usageSummaries]);

  // Toggle agent selection
  function toggleAgent(id: string) {
    setSelectedAgents(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelectedAgents(new Set(usageSummaries.map(s => s.agent_id)));
  }

  function selectNone() {
    setSelectedAgents(new Set());
  }

  // Chart theme colors
  const gridColor = isDark ? '#374151' : '#e5e7eb';
  const tickColor = isDark ? '#9ca3af' : '#6b7280';

  if (loading) {
    return (
      <div>
        <Skeleton className="h-8 w-40 mb-6" />
        <div className="grid grid-cols-3 gap-4 mb-6">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-24" />)}
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (error) {
    return <div className="text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 p-4 rounded">Error: {error}</div>;
  }

  // Compute summary metrics
  const totalLifetime = usageSummaries
    .filter(s => selectedAgents.has(s.agent_id))
    .reduce((sum, s) => sum + totalTokens(s.lifetime), 0);
  const totalToday = usageSummaries
    .filter(s => selectedAgents.has(s.agent_id))
    .reduce((sum, s) => sum + totalTokens(s.today), 0);
  const avgPerAgent = selectedAgents.size > 0 ? totalLifetime / selectedAgents.size : 0;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Token Usage</h2>
        {/* View toggle */}
        <div className="flex bg-gray-100 dark:bg-gray-800 rounded-lg p-0.5">
          {(['daily', 'overall'] as ViewMode[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-4 py-1.5 text-sm rounded-md capitalize transition-colors ${
                view === v
                  ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <MetricCard label="Total Lifetime" value={formatTokens(totalLifetime)} sub={`${selectedAgents.size} agents`} />
        <MetricCard label="Today" value={formatTokens(totalToday)} />
        <MetricCard label="Avg per Agent" value={formatTokens(avgPerAgent)} />
      </div>

      {/* Agent filter */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Agents:</span>
          <button onClick={selectAll} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">All</button>
          <button onClick={selectNone} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">None</button>
        </div>
        <div className="flex flex-wrap gap-2">
          {usageSummaries.map((s) => (
            <button
              key={s.agent_id}
              onClick={() => toggleAgent(s.agent_id)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors border ${
                selectedAgents.has(s.agent_id)
                  ? 'border-transparent text-white'
                  : 'border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 bg-transparent'
              }`}
              style={selectedAgents.has(s.agent_id) ? { backgroundColor: agentColorMap[s.agent_id] } : undefined}
            >
              {s.agent_id}
            </button>
          ))}
        </div>
      </div>

      {/* Charts */}
      {view === 'daily' ? (
        <DailyView
          agentUsages={agentUsages}
          selectedAgents={selectedAgents}
          agentColorMap={agentColorMap}
          dateRange={dateRange}
          setDateRange={setDateRange}
          gridColor={gridColor}
          tickColor={tickColor}
        />
      ) : (
        <OverallView
          usageSummaries={usageSummaries}
          agentUsages={agentUsages}
          selectedAgents={selectedAgents}
          agentColorMap={agentColorMap}
          gridColor={gridColor}
          tickColor={tickColor}
        />
      )}
    </div>
  );
}

// ---------- Daily View ----------
function DailyView({
  agentUsages, selectedAgents, agentColorMap, dateRange, setDateRange, gridColor, tickColor,
}: {
  agentUsages: Record<string, AgentUsage>;
  selectedAgents: Set<string>;
  agentColorMap: Record<string, string>;
  dateRange: DateRange;
  setDateRange: (r: DateRange) => void;
  gridColor: string;
  tickColor: string;
}) {
  // Build merged daily data: { date, agent1: total, agent2: total, ... }
  const chartData = useMemo(() => {
    const dateMap: Record<string, Record<string, number>> = {};

    for (const [agentId, usage] of Object.entries(agentUsages)) {
      if (!selectedAgents.has(agentId)) continue;
      for (const day of usage.daily_totals) {
        if (!dateMap[day.date]) dateMap[day.date] = {};
        dateMap[day.date][agentId] = totalTokens(day);
      }
    }

    return Object.entries(dateMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-dateRange)
      .map(([date, agents]) => ({ date: date.slice(5), ...agents })); // MM-DD format
  }, [agentUsages, selectedAgents, dateRange]);

  const activeAgentIds = [...selectedAgents].filter(id => id in agentUsages);

  if (Object.keys(agentUsages).length === 0) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-8">
        <div className="animate-pulse space-y-3">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">Daily Token Usage</h3>
        <div className="flex bg-gray-100 dark:bg-gray-800 rounded p-0.5">
          {([7, 14, 30] as DateRange[]).map((r) => (
            <button
              key={r}
              onClick={() => setDateRange(r)}
              className={`px-3 py-1 text-xs rounded transition-colors ${
                dateRange === r
                  ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {r}d
            </button>
          ))}
        </div>
      </div>

      {chartData.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-12">No daily data available for selected agents.</p>
      ) : (
        <ResponsiveContainer width="100%" height={360}>
          <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey="date" tick={{ fill: tickColor, fontSize: 11 }} />
            <YAxis tick={{ fill: tickColor, fontSize: 11 }} tickFormatter={formatTokens} />
            <Tooltip content={<DailyTooltip />} />
            <Legend wrapperStyle={{ fontSize: '12px' }} />
            {activeAgentIds.map((agentId) => (
              <Bar
                key={agentId}
                dataKey={agentId}
                name={agentId}
                stackId="tokens"
                fill={agentColorMap[agentId]}
                radius={[0, 0, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ---------- Overall View ----------
function OverallView({
  usageSummaries, agentUsages, selectedAgents, agentColorMap, gridColor, tickColor,
}: {
  usageSummaries: AgentUsageSummary[];
  agentUsages: Record<string, AgentUsage>;
  selectedAgents: Set<string>;
  agentColorMap: Record<string, string>;
  gridColor: string;
  tickColor: string;
}) {
  // Pie chart data
  const pieData = useMemo(() => {
    const filtered = usageSummaries.filter(s => selectedAgents.has(s.agent_id));
    const total = filtered.reduce((sum, s) => sum + totalTokens(s.lifetime), 0);
    return filtered.map(s => {
      const val = totalTokens(s.lifetime);
      return {
        name: s.agent_id,
        value: val,
        percent: total > 0 ? val / total : 0,
        fill: agentColorMap[s.agent_id],
      };
    }).filter(d => d.value > 0).sort((a, b) => b.value - a.value);
  }, [usageSummaries, selectedAgents, agentColorMap]);

  // Ranking data for table
  const rankingData = useMemo(() => {
    return usageSummaries
      .filter(s => selectedAgents.has(s.agent_id))
      .map(s => ({
        agent_id: s.agent_id,
        today: s.today,
        lifetime: s.lifetime,
        todayTotal: totalTokens(s.today),
        lifetimeTotal: totalTokens(s.lifetime),
      }))
      .sort((a, b) => b.lifetimeTotal - a.lifetimeTotal);
  }, [usageSummaries, selectedAgents]);

  // Merged by_model data
  const modelData = useMemo(() => {
    const merged: Record<string, TokenTotals> = {};
    for (const [agentId, usage] of Object.entries(agentUsages)) {
      if (!selectedAgents.has(agentId)) continue;
      for (const [model, totals] of Object.entries(usage.by_model)) {
        if (!merged[model]) {
          merged[model] = { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, message_count: 0 };
        }
        merged[model].input_tokens += totals.input_tokens;
        merged[model].output_tokens += totals.output_tokens;
        merged[model].cache_read_tokens += totals.cache_read_tokens;
        merged[model].cache_write_tokens += totals.cache_write_tokens;
        merged[model].message_count += totals.message_count;
      }
    }
    return Object.entries(merged)
      .sort(([, a], [, b]) => totalTokens(b) - totalTokens(a));
  }, [agentUsages, selectedAgents]);

  return (
    <div className="space-y-6">
      {/* Pie + Ranking */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pie chart */}
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
          <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4">Agent Share (Lifetime)</h3>
          {pieData.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-12">No data</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={110}
                  paddingAngle={2}
                  label={({ name, percent }: any) => `${name} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip content={<PieTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Ranking table */}
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
          <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4">Agent Ranking</h3>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Agent</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Today</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Lifetime</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {rankingData.map((r) => (
                <tr key={r.agent_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: agentColorMap[r.agent_id] }} />
                      <span className="text-gray-800 dark:text-gray-200">{r.agent_id}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right text-blue-600 dark:text-blue-400">{formatTokens(r.todayTotal)}</td>
                  <td className="px-3 py-2 text-right text-blue-600 dark:text-blue-400">{formatTokens(r.lifetimeTotal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Token breakdown by type */}
      <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4">Token Breakdown</h3>
        {(() => {
          // Aggregate token types across selected agents
          const breakdown = usageSummaries
            .filter(s => selectedAgents.has(s.agent_id))
            .reduce(
              (acc, s) => ({
                input: acc.input + s.lifetime.input_tokens,
                output: acc.output + s.lifetime.output_tokens,
                cache_read: acc.cache_read + s.lifetime.cache_read_tokens,
                cache_write: acc.cache_write + s.lifetime.cache_write_tokens,
              }),
              { input: 0, output: 0, cache_read: 0, cache_write: 0 }
            );
          const barData = [
            { name: 'Input', value: breakdown.input, fill: '#3b82f6' },
            { name: 'Output', value: breakdown.output, fill: '#10b981' },
            { name: 'Cache Read', value: breakdown.cache_read, fill: '#8b5cf6' },
            { name: 'Cache Write', value: breakdown.cache_write, fill: '#f59e0b' },
          ];
          return (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={barData} layout="vertical" margin={{ top: 5, right: 30, left: 80, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                <XAxis type="number" tick={{ fill: tickColor, fontSize: 11 }} tickFormatter={formatTokens} />
                <YAxis type="category" dataKey="name" tick={{ fill: tickColor, fontSize: 12 }} width={75} />
                <Tooltip formatter={(value) => formatTokens(Number(value))} />
                <Bar dataKey="value" name="Tokens" radius={[0, 4, 4, 0]}>
                  {barData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          );
        })()}
      </div>

      {/* By Model */}
      {modelData.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 p-4">
          <h3 className="font-semibold text-gray-800 dark:text-gray-100 mb-4">By Model</h3>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Model</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Input</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Output</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Cache R</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Cache W</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Total</th>
                <th className="text-right px-3 py-2 font-medium text-gray-600 dark:text-gray-300">Msgs</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {modelData.map(([model, totals]) => (
                <tr key={model} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                  <td className="px-3 py-2 text-gray-800 dark:text-gray-200 font-mono text-xs">{model}</td>
                  <td className="px-3 py-2 text-right text-blue-600 dark:text-blue-400">{formatTokens(totals.input_tokens)}</td>
                  <td className="px-3 py-2 text-right text-green-600 dark:text-green-400">{formatTokens(totals.output_tokens)}</td>
                  <td className="px-3 py-2 text-right text-purple-600 dark:text-purple-400">{formatTokens(totals.cache_read_tokens)}</td>
                  <td className="px-3 py-2 text-right text-orange-600 dark:text-orange-400">{formatTokens(totals.cache_write_tokens)}</td>
                  <td className="px-3 py-2 text-right font-medium text-gray-800 dark:text-gray-200">{formatTokens(totalTokens(totals))}</td>
                  <td className="px-3 py-2 text-right text-gray-600 dark:text-gray-400">{totals.message_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
