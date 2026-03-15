import { useEffect, useState } from 'react';
import { fetchAgentUsage, refreshAgentUsage } from '../api/agents';
import type { AgentUsage, TokenTotals } from '../types/agent';
import { formatTokens } from '../utils/format';

function TokenStat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="text-center">
      <div className={`text-lg font-bold ${color}`}>{formatTokens(value)}</div>
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
    </div>
  );
}

function TokenBreakdown({ title, data }: { title: string; data: TokenTotals }) {
  const total = data.input_tokens + data.output_tokens + data.cache_read_tokens + data.cache_write_tokens;
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">{title}</h4>
        <span className="text-xs text-gray-400">{formatTokens(total)} total</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <TokenStat label="Input" value={data.input_tokens} color="text-blue-600 dark:text-blue-400" />
        <TokenStat label="Output" value={data.output_tokens} color="text-green-600 dark:text-green-400" />
        <TokenStat label="Cache Read" value={data.cache_read_tokens} color="text-purple-600 dark:text-purple-400" />
        <TokenStat label="Cache Write" value={data.cache_write_tokens} color="text-orange-600 dark:text-orange-400" />
      </div>
    </div>
  );
}

function ModelTable({ byModel }: { byModel: Record<string, TokenTotals> }) {
  const models = Object.entries(byModel).sort(
    ([, a], [, b]) => (b.input_tokens + b.output_tokens) - (a.input_tokens + a.output_tokens)
  );

  if (models.length === 0) return null;

  return (
    <div>
      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">By Model</h4>
      <table className="w-full text-sm">
        <thead className="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th className="text-left px-3 py-1.5 font-medium text-gray-600 dark:text-gray-300">Model</th>
            <th className="text-right px-3 py-1.5 font-medium text-gray-600 dark:text-gray-300">Input</th>
            <th className="text-right px-3 py-1.5 font-medium text-gray-600 dark:text-gray-300">Output</th>
            <th className="text-right px-3 py-1.5 font-medium text-gray-600 dark:text-gray-300">Cache R</th>
            <th className="text-right px-3 py-1.5 font-medium text-gray-600 dark:text-gray-300">Cache W</th>
            <th className="text-right px-3 py-1.5 font-medium text-gray-600 dark:text-gray-300">Messages</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
          {models.map(([model, usage]) => (
            <tr key={model} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
              <td className="px-3 py-1.5 text-gray-800 dark:text-gray-200 font-mono text-xs">{model}</td>
              <td className="px-3 py-1.5 text-right text-blue-600 dark:text-blue-400">{formatTokens(usage.input_tokens)}</td>
              <td className="px-3 py-1.5 text-right text-green-600 dark:text-green-400">{formatTokens(usage.output_tokens)}</td>
              <td className="px-3 py-1.5 text-right text-purple-600 dark:text-purple-400">{formatTokens(usage.cache_read_tokens)}</td>
              <td className="px-3 py-1.5 text-right text-orange-600 dark:text-orange-400">{formatTokens(usage.cache_write_tokens)}</td>
              <td className="px-3 py-1.5 text-right text-gray-600 dark:text-gray-400">{usage.message_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DailyChart({ dailyTotals }: { dailyTotals: AgentUsage['daily_totals'] }) {
  // Show last 14 days
  const recent = dailyTotals.slice(-14);
  if (recent.length === 0) return null;

  const maxTokens = Math.max(...recent.map(d => d.input_tokens + d.output_tokens + d.cache_read_tokens + d.cache_write_tokens), 1);

  return (
    <div>
      <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Daily Activity (last 14 days)</h4>
      <div className="flex items-end gap-1" style={{ height: '80px' }}>
        {recent.map((day) => {
          const total = day.input_tokens + day.output_tokens + day.cache_read_tokens + day.cache_write_tokens;
          const height = Math.max((total / maxTokens) * 100, 2);
          const dateLabel = day.date.slice(5); // MM-DD
          return (
            <div key={day.date} className="flex-1 flex flex-col items-center group relative">
              <div
                className="w-full bg-blue-500 dark:bg-blue-600 rounded-t hover:bg-blue-600 dark:hover:bg-blue-500 transition-colors"
                style={{ height: `${height}%` }}
                title={`${day.date}: ${formatTokens(total)} tokens`}
              />
              <div className="text-[9px] text-gray-400 mt-1 truncate w-full text-center">{dateLabel}</div>
              {/* Tooltip */}
              <div className="absolute bottom-full mb-1 hidden group-hover:block bg-gray-900 text-white text-xs px-2 py-1 rounded whitespace-nowrap z-10">
                {day.date}: {formatTokens(total)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function TokenUsagePanel({ agentId }: { agentId: string }) {
  const [usage, setUsage] = useState<AgentUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const data = await fetchAgentUsage(agentId);
        if (active) setUsage(data);
      } catch {
        // Usage data may not be available yet
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, [agentId]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const data = await refreshAgentUsage(agentId);
      setUsage(data);
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }

  const hasData = usage && usage.lifetime.message_count > 0;

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800">
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
        <h3 className="font-semibold text-gray-800 dark:text-gray-100">Token Usage</h3>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="text-xs px-2 py-1 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          {refreshing ? 'Scanning...' : 'Refresh'}
        </button>
      </div>
      <div className="p-4 space-y-5">
        {loading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-12 bg-gray-200 dark:bg-gray-700 rounded" />
            <div className="h-12 bg-gray-200 dark:bg-gray-700 rounded" />
          </div>
        ) : !hasData ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            No usage data yet. Click Refresh to scan session files.
          </p>
        ) : (
          <>
            <TokenBreakdown title="Today" data={usage!.today} />
            <div className="border-t border-gray-100 dark:border-gray-800 pt-4">
              <TokenBreakdown title="Lifetime" data={usage!.lifetime} />
            </div>
            <div className="border-t border-gray-100 dark:border-gray-800 pt-4">
              <DailyChart dailyTotals={usage!.daily_totals} />
            </div>
            <div className="border-t border-gray-100 dark:border-gray-800 pt-4">
              <ModelTable byModel={usage!.by_model} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
