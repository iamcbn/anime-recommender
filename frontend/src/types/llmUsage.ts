// frontend/src/types/llmUsage.ts

export type LlmLayer = 'nli' | 'retrieval' | 'presentation';

export interface DailyUsageItem {
  date: string; // YYYY-MM-DD
  layer: LlmLayer | string;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  cache_hit_count: number;
  fallback_count: number;
}

export interface LayerBudgetStatus {
  layer: LlmLayer | string;
  current_usage: number;
  limit: number;
  remaining: number;
  soft_limit_hit: boolean;
  hard_limit_hit: boolean;
  usage_ratio: number;
}

export type BudgetMap = Record<string, LayerBudgetStatus>;

export interface LlmUsageSummary {
  todayTokens: number;
  todayCost: number;
  totalTokensInRange: number;
  totalCostInRange: number;
  totalRequestsInRange: number;
  healthyLayersCount: number;
  softLimitCount: number;
  hardLimitCount: number;
}
