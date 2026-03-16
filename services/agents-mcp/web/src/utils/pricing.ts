/**
 * Claude model pricing (per million tokens, USD).
 * Updated: March 2026
 *
 * To update prices, edit MODEL_PRICES below.
 */

import type { TokenTotals } from '../types/agent';

export interface ModelPricing {
  input: number;        // $ per 1M input tokens
  output: number;       // $ per 1M output tokens
  cache_read: number;   // $ per 1M cache read tokens
  cache_write: number;  // $ per 1M cache write tokens (5min TTL)
}

/**
 * Pricing per model family. Keys are matched against model names
 * using startsWith, so "claude-opus-4" matches "claude-opus-4-20260301".
 */
const MODEL_PRICES: Record<string, ModelPricing> = {
  // Opus 4.6 / 4.5
  'claude-opus-4': { input: 5, output: 25, cache_read: 0.50, cache_write: 6.25 },
  // Sonnet 4.6 / 4.5 / 4
  'claude-sonnet-4': { input: 3, output: 15, cache_read: 0.30, cache_write: 3.75 },
  // Haiku 4.5
  'claude-haiku-4': { input: 1, output: 5, cache_read: 0.10, cache_write: 1.25 },
  // Haiku 3.5
  'claude-3-5-haiku': { input: 0.80, output: 4, cache_read: 0.08, cache_write: 1.00 },
  // Sonnet 3.5 (legacy)
  'claude-3-5-sonnet': { input: 3, output: 15, cache_read: 0.30, cache_write: 3.75 },
  // Opus 3.5 (legacy)
  'claude-3-5-opus': { input: 5, output: 25, cache_read: 0.50, cache_write: 6.25 },
};

// Default pricing when model is not recognized (use Sonnet pricing as reasonable default)
export const DEFAULT_PRICING: ModelPricing = { input: 3, output: 15, cache_read: 0.30, cache_write: 3.75 };

/**
 * Find the pricing for a model name.
 * Matches by prefix, e.g. "claude-sonnet-4-20260301" matches "claude-sonnet-4".
 */
export function getModelPricing(modelName: string): ModelPricing {
  const normalized = modelName.toLowerCase();
  for (const [prefix, pricing] of Object.entries(MODEL_PRICES)) {
    if (normalized.startsWith(prefix)) return pricing;
  }
  return DEFAULT_PRICING;
}

/**
 * Calculate cost (in USD) for a set of token totals and a specific model.
 */
export function calculateCost(totals: TokenTotals, modelName: string): number {
  const pricing = getModelPricing(modelName);
  return (
    (totals.input_tokens * pricing.input +
     totals.output_tokens * pricing.output +
     totals.cache_read_tokens * pricing.cache_read +
     totals.cache_write_tokens * pricing.cache_write) / 1_000_000
  );
}

/**
 * Calculate cost for token totals using a weighted average pricing.
 * Used when model information is not available (e.g., aggregated daily totals).
 * Falls back to DEFAULT_PRICING.
 */
export function calculateCostDefault(totals: TokenTotals): number {
  return (
    (totals.input_tokens * DEFAULT_PRICING.input +
     totals.output_tokens * DEFAULT_PRICING.output +
     totals.cache_read_tokens * DEFAULT_PRICING.cache_read +
     totals.cache_write_tokens * DEFAULT_PRICING.cache_write) / 1_000_000
  );
}

/**
 * Calculate total cost across multiple models from a by_model map.
 */
export function calculateTotalCostByModel(byModel: Record<string, TokenTotals>): number {
  let total = 0;
  for (const [model, totals] of Object.entries(byModel)) {
    total += calculateCost(totals, model);
  }
  return total;
}

/**
 * Format cost as USD string.
 */
export function formatCost(cost: number): string {
  if (cost >= 1000) return `$${(cost / 1000).toFixed(1)}K`;
  if (cost >= 100) return `$${cost.toFixed(0)}`;
  if (cost >= 10) return `$${cost.toFixed(1)}`;
  if (cost >= 1) return `$${cost.toFixed(2)}`;
  if (cost >= 0.01) return `$${cost.toFixed(2)}`;
  if (cost > 0) return `$${cost.toFixed(3)}`;
  return '$0.00';
}
