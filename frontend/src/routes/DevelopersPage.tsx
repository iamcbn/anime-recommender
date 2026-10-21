// frontend/src/routes/DevelopersPage.tsx
import React, { useState } from 'react';
import { Plus, Key, ShieldCheck, Terminal, AlertCircle } from 'lucide-react';
import { useApiKeys } from '../hooks/useApiKeys';
import { Button } from '../components/common/Button';
import { KeyQuotaBanner } from '../components/developers/KeyQuotaBanner';
import { KeyListTable } from '../components/developers/KeyListTable';
import { CreateKeyModal } from '../components/developers/CreateKeyModal';
import { RevokeKeyModal } from '../components/developers/RevokeKeyModal';
import type { KeyItem } from '../types/apiKeys';

export const DevelopersPage: React.FC = () => {
  const {
    keys,
    isLoading,
    error,
    activeKeysCount,
    isAtMaxLimit,
    createKey,
    revokeKey,
  } = useApiKeys();

  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);
  const [revokeTarget, setRevokeTarget] = useState<KeyItem | null>(null);

  return (
    <div className="flex flex-col gap-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200 dark:border-dark-800">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2.5">
            <Key className="w-6 h-6 text-brand" />
            Developer API Keys
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Manage your personal Bearer tokens for the Anime Recommender inference and retrieval API.
          </p>
        </div>

        <Button
          variant="primary"
          onClick={() => setIsCreateOpen(true)}
          disabled={isAtMaxLimit}
          icon={<Plus className="w-4 h-4" />}
        >
          Create API Key
        </Button>
      </div>

      {/* Global Error Banner if any */}
      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-700 dark:text-red-300 flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Quota Banner */}
      <KeyQuotaBanner activeCount={activeKeysCount} maxAllowed={5} />

      {/* Main Keys Table */}
      <KeyListTable
        keys={keys}
        isLoading={isLoading}
        onRevokeClick={(keyItem) => setRevokeTarget(keyItem)}
      />

      {/* Security Guidance Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4">
        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm">
          <ShieldCheck className="w-5 h-5 text-emerald-500 dark:text-emerald-400 mb-2" />
          <h4 className="text-sm font-semibold text-slate-900 dark:text-white">HMAC-SHA256 Hashed</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
            Raw keys are never stored in our database. We store salted HMAC hashes with server-side pepper protection.
          </p>
        </div>

        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm">
          <Terminal className="w-5 h-5 text-indigo-500 dark:text-indigo-400 mb-2" />
          <h4 className="text-sm font-semibold text-slate-900 dark:text-white">Per-Key Rate Limits</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
            Each key is allocated an independent rate limit of 20 requests per minute with Redis sliding window throttling.
          </p>
        </div>

        <div className="p-4 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm">
          <Key className="w-5 h-5 text-brand mb-2" />
          <h4 className="text-sm font-semibold text-slate-900 dark:text-white">Automatic 90-Day Expiry</h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
            Keys automatically expire after 90 days. Follow our zero-downtime rotation guide to rotate keys seamlessly.
          </p>
        </div>
      </div>

      {/* Modals */}
      <CreateKeyModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSubmit={createKey}
        isAtLimit={isAtMaxLimit}
      />

      <RevokeKeyModal
        keyItem={revokeTarget}
        isOpen={Boolean(revokeTarget)}
        onClose={() => setRevokeTarget(null)}
        onConfirm={revokeKey}
      />
    </div>
  );
};
