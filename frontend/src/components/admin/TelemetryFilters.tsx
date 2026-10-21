// frontend/src/components/admin/TelemetryFilters.tsx
import React from 'react';
import { Search, RotateCw } from 'lucide-react';
import type {
  TelemetryFiltersState,
  TelemetryEndpoint,
  TelemetrySource,
  TelemetryStatus,
} from '../../types/telemetry';
import { Button } from '../common/Button';

export interface TelemetryFiltersProps {
  filters: TelemetryFiltersState;
  onFilterChange: (filters: Partial<TelemetryFiltersState>) => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export const TelemetryFilters: React.FC<TelemetryFiltersProps> = ({
  filters,
  onFilterChange,
  onRefresh,
  isLoading,
}) => {
  return (
    <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4 transition-colors">
      {/* Search Input */}
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input
          type="text"
          value={filters.searchQuery}
          onChange={(e) => onFilterChange({ searchQuery: e.target.value })}
          placeholder="Filter by query content..."
          className="w-full pl-9 pr-4 py-2 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-sm text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand"
        />
      </div>

      {/* Filter Selects */}
      <div className="flex flex-wrap items-center gap-2.5 text-xs">
        {/* Source Filter */}
        <select
          value={filters.source}
          onChange={(e) => onFilterChange({ source: e.target.value as TelemetrySource })}
          className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand"
        >
          <option value="all">Source: All</option>
          <option value="user">Source: User</option>
          <option value="admin_eval">Source: Admin Eval</option>
        </select>

        {/* Endpoint Filter */}
        <select
          value={filters.endpoint}
          onChange={(e) => onFilterChange({ endpoint: e.target.value as TelemetryEndpoint })}
          className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand"
        >
          <option value="all">Endpoint: All</option>
          <option value="recommend">/recommend</option>
          <option value="admin_recommend">/admin/recommend</option>
          <option value="chat">/chat</option>
        </select>

        {/* Status Filter */}
        <select
          value={filters.status}
          onChange={(e) => onFilterChange({ status: e.target.value as TelemetryStatus })}
          className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand"
        >
          <option value="all">Status: All</option>
          <option value="ok">Status: OK</option>
          <option value="error">Status: Error</option>
        </select>

        {/* Date Presets */}
        <select
          value={filters.dateRangeDays}
          onChange={(e) => onFilterChange({ dateRangeDays: Number(e.target.value) })}
          className="px-3 py-2 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand"
        >
          <option value={1}>Last 24 Hours</option>
          <option value={7}>Last 7 Days</option>
          <option value={30}>Last 30 Days</option>
        </select>

        {/* Refresh Button */}
        <Button
          variant="secondary"
          size="sm"
          onClick={onRefresh}
          isLoading={isLoading}
          icon={<RotateCw className="w-3.5 h-3.5" />}
          title="Refresh logs"
        >
          Refresh
        </Button>
      </div>
    </div>
  );
};
