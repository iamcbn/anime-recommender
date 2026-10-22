// frontend/src/routes/AdminLlmUsagePage.tsx
import React from 'react';
import { AlertCircle, Coins } from 'lucide-react';
import { useLlmUsage } from '../hooks/useLlmUsage';
import { LlmUsageView } from '../components/admin/LlmUsageView';

export const AdminLlmUsagePage: React.FC = () => {
  const usageData = useLlmUsage(7);
  const { error } = usageData;

  return (
    <div className="flex flex-col gap-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-dark-800">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2.5">
            <Coins className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
            Admin LLM Usage Explorer
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Live token ceilings, budget safeguards, and per-layer cost breakdown across NLI, Retrieval, and Presentation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30 text-xs font-mono">
            <span className="w-2 h-2 rounded-full bg-emerald-500 dark:bg-emerald-400 animate-pulse" />
            Daily Ceilings Active
          </span>
        </div>
      </div>

      {/* Error banner if query fails */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-700 dark:text-red-300 flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Main LLM Usage Dashboard View */}
      <LlmUsageView usageData={usageData} />
    </div>
  );
};

export default AdminLlmUsagePage;
