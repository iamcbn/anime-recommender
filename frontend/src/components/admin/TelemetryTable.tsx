// frontend/src/components/admin/TelemetryTable.tsx
import React from 'react';
import { Eye, ChevronLeft, ChevronRight, Clock, AlertTriangle } from 'lucide-react';
import type { RecommendationLog } from '../../types/telemetry';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';

export interface TelemetryTableProps {
  logs: RecommendationLog[];
  isLoading: boolean;
  page: number;
  pageSize: number;
  totalCount: number;
  onPageChange: (newPage: number) => void;
  onInspectClick: (log: RecommendationLog) => void;
}

export const TelemetryTable: React.FC<TelemetryTableProps> = ({
  logs,
  isLoading,
  page,
  pageSize,
  totalCount,
  onPageChange,
  onInspectClick,
}) => {
  const formatTime = (isoStr: string) => {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
      ' ' +
      d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  const getLatencyColor = (ms: number | null) => {
    if (!ms) return 'text-slate-400';
    if (ms < 200) return 'text-emerald-600 dark:text-emerald-400';
    if (ms < 500) return 'text-amber-600 dark:text-amber-400';
    return 'text-red-600 dark:text-red-400';
  };

  const totalPages = Math.ceil(totalCount / pageSize) || 1;

  if (isLoading && logs.length === 0) {
    return (
      <div className="w-full py-16 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 gap-3 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm">
        <Clock className="w-6 h-6 animate-spin text-brand" />
        <span className="text-sm">Fetching telemetry records from PostgREST...</span>
      </div>
    );
  }

  if (logs.length === 0) {
    return (
      <div className="w-full py-16 flex flex-col items-center justify-center text-center p-6 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm">
        <AlertTriangle className="w-6 h-6 text-slate-400 mb-2" />
        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">No Telemetry Logs Found</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mt-1">
          No records match your selected filters. Adjust your source, endpoint, or date range.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 shadow-sm flex flex-col overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-slate-700 dark:text-slate-300">
          <thead className="bg-slate-50 dark:bg-dark-950 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-dark-800">
            <tr>
              <th className="px-5 py-3.5">Timestamp</th>
              <th className="px-5 py-3.5">Endpoint</th>
              <th className="px-5 py-3.5">Source</th>
              <th className="px-5 py-3.5">Query Preview</th>
              <th className="px-5 py-3.5">Results</th>
              <th className="px-5 py-3.5">Latency</th>
              <th className="px-5 py-3.5">Status</th>
              <th className="px-5 py-3.5 text-right">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-dark-800 text-xs">
            {logs.map((log) => (
              <tr key={log.id} className="hover:bg-slate-50 dark:hover:bg-dark-800/50 transition-colors">
                <td className="px-5 py-3.5 text-slate-500 dark:text-slate-400 font-mono whitespace-nowrap">
                  {formatTime(log.created_at)}
                </td>
                <td className="px-5 py-3.5">
                  <span className="font-mono text-indigo-600 dark:text-indigo-400 font-semibold">{log.endpoint}</span>
                </td>
                <td className="px-5 py-3.5">
                  <Badge variant={log.source === 'admin_eval' ? 'brand' : 'neutral'} size="sm">
                    {log.source}
                  </Badge>
                </td>
                <td className="px-5 py-3.5 max-w-[240px] truncate text-slate-900 dark:text-slate-200" title={log.query}>
                  {log.query}
                </td>
                <td className="px-5 py-3.5 font-mono text-slate-600 dark:text-slate-300">
                  {log.results_count} <span className="text-slate-400 dark:text-slate-500">/ {log.top_k}</span>
                </td>
                <td className={`px-5 py-3.5 font-mono font-medium ${getLatencyColor(log.total_ms)}`}>
                  {log.total_ms ? `${Math.round(log.total_ms)} ms` : '—'}
                </td>
                <td className="px-5 py-3.5">
                  <Badge variant={log.status === 'ok' ? 'success' : 'danger'} size="sm">
                    {log.status}
                  </Badge>
                </td>
                <td className="px-5 py-3.5 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onInspectClick(log)}
                    className="text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                    icon={<Eye className="w-3.5 h-3.5" />}
                  >
                    Inspect
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="p-4 border-t border-slate-200 dark:border-dark-800 bg-slate-50 dark:bg-dark-950 flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
        <div>
          Showing <span className="font-semibold text-slate-900 dark:text-white">{page * pageSize + 1}</span> to{' '}
          <span className="font-semibold text-slate-900 dark:text-white">
            {Math.min((page + 1) * pageSize, totalCount)}
          </span>{' '}
          of <span className="font-semibold text-slate-900 dark:text-white">{totalCount}</span> entries
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page === 0 || isLoading}
            icon={<ChevronLeft className="w-3.5 h-3.5" />}
          >
            Prev
          </Button>

          <span className="px-2 text-slate-700 dark:text-slate-300 font-mono">
            {page + 1} / {totalPages}
          </span>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages - 1 || isLoading}
            icon={<ChevronRight className="w-3.5 h-3.5" />}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
};
