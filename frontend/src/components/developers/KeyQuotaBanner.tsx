// frontend/src/components/developers/KeyQuotaBanner.tsx
import React from 'react';
import { KeyRound, Info } from 'lucide-react';

export const KeyQuotaBanner: React.FC<{ activeCount: number; maxAllowed?: number }> = ({
  activeCount,
  maxAllowed = 5,
}) => {
  const isFull = activeCount >= maxAllowed;

  return (
    <div
      className={`p-4 rounded-xl border flex items-center justify-between gap-4 transition-colors ${
        isFull
          ? 'bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950/20 dark:border-amber-500/30 dark:text-amber-300'
          : 'bg-white border-slate-200 text-slate-700 dark:bg-dark-900 dark:border-dark-800 dark:text-slate-300 shadow-sm'
      }`}
    >
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${isFull ? 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400' : 'bg-brand/10 text-brand'}`}>
          <KeyRound className="w-5 h-5" />
        </div>
        <div>
          <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
            Active Developer Keys ({activeCount} / {maxAllowed})
          </h4>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {isFull
              ? 'You have reached the limit of 5 active keys. Revoke an unused key before creating a new one.'
              : 'Each developer account can maintain up to 5 active API keys simultaneously.'}
          </p>
        </div>
      </div>

      <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-dark-950 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-dark-800">
        <Info className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
        <span>Rate limit: 20 req/min per key</span>
      </div>
    </div>
  );
};
