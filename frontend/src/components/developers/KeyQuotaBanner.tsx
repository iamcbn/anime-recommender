// frontend/src/components/developers/KeyQuotaBanner.tsx
import React from 'react';

export const KeyQuotaBanner: React.FC<{ activeCount: number; maxAllowed?: number }> = ({
  activeCount,
  maxAllowed = 5,
}) => {
  const isFull = activeCount >= maxAllowed;

  return (
    <div
      className={`px-4 py-2.5 rounded-lg border flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs transition-colors ${
        isFull
          ? 'bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950/20 dark:border-amber-500/30 dark:text-amber-300'
          : 'bg-white border-slate-200 text-slate-600 dark:bg-dark-900 dark:border-dark-800 dark:text-slate-400'
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="font-mono font-medium text-slate-900 dark:text-white">
          Active keys: {activeCount} / {maxAllowed}
        </span>
        {isFull && (
          <span>
            — Limit reached. Revoke an unused key before creating another.
          </span>
        )}
      </div>

      <div className="font-mono text-slate-500 dark:text-slate-400">
        Rate limit: 20 req/min
      </div>
    </div>
  );
};
