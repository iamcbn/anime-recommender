// frontend/src/routes/AdminTelemetryPage.tsx
import React, { useState } from 'react';
import { Shield, AlertCircle } from 'lucide-react';
import { useTelemetryLogs } from '../hooks/useTelemetryLogs';
import { TelemetryStatsBar } from '../components/admin/TelemetryStatsBar';
import { TelemetryFilters } from '../components/admin/TelemetryFilters';
import { TelemetryTable } from '../components/admin/TelemetryTable';
import { LogDetailModal } from '../components/admin/LogDetailModal';
import type { RecommendationLog } from '../types/telemetry';

export const AdminTelemetryPage: React.FC = () => {
  const {
    logs,
    isLoading,
    error,
    filters,
    pagination,
    stats,
    updateFilters,
    setPage,
    refetch,
  } = useTelemetryLogs();

  const [inspectTarget, setInspectTarget] = useState<RecommendationLog | null>(null);

  return (
    <div className="flex flex-col gap-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-dark-800">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2.5">
            <Shield className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
            Admin Telemetry Explorer
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Real-time query performance, latency breakdown, and recommendation logs queried directly via PostgREST under RLS.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30 text-xs font-mono">
            <span className="w-2 h-2 rounded-full bg-emerald-500 dark:bg-emerald-400 animate-pulse" />
            Live Hot Storage (Days 0-30)
          </span>
        </div>
      </div>

      {/* Error banner if RLS or query fails */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-700 dark:text-red-300 flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Aggregate Metrics Bar */}
      <TelemetryStatsBar stats={stats} totalCount={pagination.totalCount} />

      {/* Filter Toolbar */}
      <TelemetryFilters
        filters={filters}
        onFilterChange={updateFilters}
        onRefresh={refetch}
        isLoading={isLoading}
      />

      {/* Logs Table */}
      <TelemetryTable
        logs={logs}
        isLoading={isLoading}
        page={pagination.page}
        pageSize={pagination.pageSize}
        totalCount={pagination.totalCount}
        onPageChange={setPage}
        onInspectClick={(log) => setInspectTarget(log)}
      />

      {/* Inspect Detail Modal */}
      <LogDetailModal
        log={inspectTarget}
        isOpen={Boolean(inspectTarget)}
        onClose={() => setInspectTarget(null)}
      />
    </div>
  );
};
