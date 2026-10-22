// frontend/src/hooks/useLlmUsage.ts
import { useState, useEffect, useCallback, useMemo } from 'react';
import { env } from '../config/env';
import { useAuth } from './useAuth';
import type {
  DailyUsageItem,
  BudgetMap,
  LlmUsageSummary,
} from '../types/llmUsage';

export interface UseLlmUsageResult {
  dailyUsage: DailyUsageItem[];
  budget: BudgetMap | null;
  isLoading: boolean;
  error: string | null;
  days: number;
  selectedLayer: string;
  setDays: (days: number) => void;
  setSelectedLayer: (layer: string) => void;
  refetch: () => Promise<void>;
  summary: LlmUsageSummary;
}

export const useLlmUsage = (initialDays: number = 7): UseLlmUsageResult => {
  const { session, isAdmin } = useAuth();
  const [dailyUsage, setDailyUsage] = useState<DailyUsageItem[]>([]);
  const [budget, setBudget] = useState<BudgetMap | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [days, setDays] = useState<number>(initialDays);
  const [selectedLayer, setSelectedLayer] = useState<string>('all');

  const fetchData = useCallback(async () => {
    if (!session || !isAdmin) {
      setDailyUsage([]);
      setBudget(null);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    const token = session.access_token;
    const headers: Record<string, string> = {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    };

    try {
      // 1. Fetch current live budget
      const budgetUrl = `${env.API_BASE_URL}/admin/llm-usage/current-budget`;
      const budgetPromise = fetch(budgetUrl, { headers }).then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const msg = errData?.detail?.error?.message || errData?.detail || `Budget error ${res.status}`;
          throw new Error(msg);
        }
        return res.json() as Promise<BudgetMap>;
      });

      // 2. Fetch daily usage aggregation
      const layerQuery = selectedLayer !== 'all' ? `&layer=${encodeURIComponent(selectedLayer)}` : '';
      const dailyUrl = `${env.API_BASE_URL}/admin/llm-usage/daily?days=${days}${layerQuery}`;
      const dailyPromise = fetch(dailyUrl, { headers }).then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const msg = errData?.detail?.error?.message || errData?.detail || `Usage query error ${res.status}`;
          throw new Error(msg);
        }
        return res.json() as Promise<DailyUsageItem[]>;
      });

      const [budgetData, dailyData] = await Promise.all([budgetPromise, dailyPromise]);
      setBudget(budgetData);
      setDailyUsage(Array.isArray(dailyData) ? dailyData : []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to retrieve LLM usage telemetry.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [session, isAdmin, days, selectedLayer]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Derived summary calculations
  const summary = useMemo<LlmUsageSummary>(() => {
    const todayStr = new Date().toISOString().split('T')[0];

    const todayItems = dailyUsage.filter((item) => item.date === todayStr);
    const todayTokensFromItems = todayItems.reduce((acc, item) => acc + item.total_tokens, 0);
    const todayCostFromItems = todayItems.reduce((acc, item) => acc + item.estimated_cost_usd, 0);

    // If budget map exists, we can also use live budget numbers for today's tokens
    let todayLiveTokens = 0;
    let healthyCount = 0;
    let softLimitCount = 0;
    let hardLimitCount = 0;

    if (budget) {
      Object.values(budget).forEach((b) => {
        todayLiveTokens += b.current_usage;
        if (b.hard_limit_hit) {
          hardLimitCount++;
        } else if (b.soft_limit_hit) {
          softLimitCount++;
        } else {
          healthyCount++;
        }
      });
    }

    const totalTokensInRange = dailyUsage.reduce((acc, item) => acc + item.total_tokens, 0);
    const totalCostInRange = dailyUsage.reduce((acc, item) => acc + item.estimated_cost_usd, 0);
    const totalRequestsInRange = dailyUsage.reduce((acc, item) => acc + item.request_count, 0);

    return {
      todayTokens: Math.max(todayTokensFromItems, todayLiveTokens),
      todayCost: Number(todayCostFromItems.toFixed(4)),
      totalTokensInRange,
      totalCostInRange: Number(totalCostInRange.toFixed(4)),
      totalRequestsInRange,
      healthyLayersCount: healthyCount,
      softLimitCount,
      hardLimitCount,
    };
  }, [dailyUsage, budget]);

  return {
    dailyUsage,
    budget,
    isLoading,
    error,
    days,
    selectedLayer,
    setDays,
    setSelectedLayer,
    refetch: fetchData,
    summary,
  };
};
