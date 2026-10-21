// frontend/src/hooks/useTelemetryLogs.ts
import { useState, useEffect, useCallback, useMemo } from 'react';
import { supabase } from '../lib/supabase';
import type {
  RecommendationLog,
  TelemetryFiltersState,
  PaginationState,
} from '../types/telemetry';
import { useAuth } from './useAuth';

export const useTelemetryLogs = () => {
  const { session, isAdmin } = useAuth();
  const [logs, setLogs] = useState<RecommendationLog[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [filters, setFilters] = useState<TelemetryFiltersState>({
    endpoint: 'all',
    source: 'all',
    status: 'all',
    dateRangeDays: 7,
    searchQuery: '',
  });

  const [pagination, setPagination] = useState<PaginationState>({
    page: 0,
    pageSize: 25,
    totalCount: 0,
  });

  const fetchLogs = useCallback(async () => {
    if (!session || !isAdmin) {
      setLogs([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Hard cap limit <= 500
      const limit = Math.min(pagination.pageSize, 500);
      const from = pagination.page * limit;
      const to = from + limit - 1;

      let query = supabase
        .schema('telemetry')
        .from('recommendation_logs')
        .select('*', { count: 'exact' });

      // Apply source filter
      if (filters.source !== 'all') {
        query = query.eq('source', filters.source);
      }

      // Apply endpoint filter
      if (filters.endpoint !== 'all') {
        query = query.eq('endpoint', filters.endpoint);
      }

      // Apply status filter
      if (filters.status !== 'all') {
        query = query.eq('status', filters.status);
      }

      // Apply date range cutoff
      if (filters.dateRangeDays > 0) {
        const cutoffDate = new Date();
        cutoffDate.setDate(cutoffDate.getDate() - filters.dateRangeDays);
        query = query.gte('created_at', cutoffDate.toISOString());
      }

      // Apply search query filter if provided
      if (filters.searchQuery.trim()) {
        const term = filters.searchQuery.trim();
        query = query.ilike('query', `%${term}%`);
      }

      // Enforce descending order by created_at and bounded range
      query = query.order('created_at', { ascending: false }).range(from, to);

      const { data, count, error: queryError } = await query;

      if (queryError) {
        throw new Error(queryError.message);
      }

      setLogs((data as RecommendationLog[]) || []);
      setPagination((prev) => ({
        ...prev,
        totalCount: count || 0,
      }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to query telemetry logs';
      setError(msg);
      setLogs([]);
    } finally {
      setIsLoading(false);
    }
  }, [session, isAdmin, filters, pagination.page, pagination.pageSize]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // Aggregate stats derived from current logs
  const stats = useMemo(() => {
    const totalInBatch = logs.length;
    const errorsInBatch = logs.filter((l) => l.status === 'error').length;
    const latencies = logs
      .map((l) => l.total_ms)
      .filter((ms): ms is number => typeof ms === 'number' && ms > 0)
      .sort((a, b) => a - b);

    let p95Latency = 0;
    if (latencies.length > 0) {
      const idx = Math.floor(latencies.length * 0.95);
      p95Latency = Math.round(latencies[Math.min(idx, latencies.length - 1)]);
    }

    const avgLatency = latencies.length
      ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
      : 0;

    return {
      totalInBatch,
      errorsInBatch,
      p95Latency,
      avgLatency,
    };
  }, [logs]);

  const updateFilters = (newFilters: Partial<TelemetryFiltersState>) => {
    setFilters((prev) => ({ ...prev, ...newFilters }));
    setPagination((prev) => ({ ...prev, page: 0 })); // reset to page 0
  };

  const setPage = (page: number) => {
    setPagination((prev) => ({ ...prev, page }));
  };

  const setPageSize = (pageSize: number) => {
    setPagination((prev) => ({ ...prev, pageSize: Math.min(pageSize, 500), page: 0 }));
  };

  return {
    logs,
    isLoading,
    error,
    filters,
    pagination,
    stats,
    updateFilters,
    setPage,
    setPageSize,
    refetch: fetchLogs,
  };
};
