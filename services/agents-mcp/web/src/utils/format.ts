import type { TokenTotals } from '../types/agent';

export function formatTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

export function totalTokens(t: TokenTotals): number {
  return t.input_tokens + t.output_tokens + t.cache_read_tokens + t.cache_write_tokens;
}
