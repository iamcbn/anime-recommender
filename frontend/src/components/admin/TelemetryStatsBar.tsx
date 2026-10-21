// frontend/src/components/admin/TelemetryStatsBar.tsx
import React from 'react';
import { Activity, Zap, AlertCircle, Clock } from 'lucide-react';

export interface TelemetryStatsBarProps {
  stats: {
    totalInBatch: number;
    errorsInBatch: number;
    p95Latency: number;
    avgLatency: number;
  };
  totalCount: number;
}

export const TelemetryStatsBar: React.FC<TelemetryStatsBarProps> = ({ stats, totalCount }) => {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex items-center gap-3">
        <div className="p-2.5 rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">
          <Activity className="w-5 h-5" />
        </div>
        <div>
          <span className="text-xs text-slate-500 dark:text-slate-400">Total Logged</span>
          <h3 className="text-xl font-bold text-slate-900 dark:text-white">{totalCount.toLocaleString()}</h3>
        </div>
      </div>

      <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex items-center gap-3">
        <div className="p-2.5 rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400">
          <Zap className="w-5 h-5" />
        </div>
        <div>
          <span className="text-xs text-slate-500 dark:text-slate-400">P95 Latency</span>
          <h3 className="text-xl font-bold text-slate-900 dark:text-white">
            {stats.p95Latency} <span className="text-xs font-normal text-slate-400 dark:text-slate-500">ms</span>
          </h3>
        </div>
      </div>

      <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex items-center gap-3">
        <div className="p-2.5 rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400">
          <Clock className="w-5 h-5" />
        </div>
        <div>
          <span className="text-xs text-slate-500 dark:text-slate-400">Avg Latency</span>
          <h3 className="text-xl font-bold text-slate-900 dark:text-white">
            {stats.avgLatency} <span className="text-xs font-normal text-slate-400 dark:text-slate-500">ms</span>
          </h3>
        </div>
      </div>

      <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm flex items-center gap-3">
        <div className={`p-2.5 rounded-lg ${stats.errorsInBatch > 0 ? 'bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
          <AlertCircle className="w-5 h-5" />
        </div>
        <div>
          <span className="text-xs text-slate-500 dark:text-slate-400">Errors (Batch)</span>
          <h3 className="text-xl font-bold text-slate-900 dark:text-white">{stats.errorsInBatch}</h3>
        </div>
      </div>
    </div>
  );
};
