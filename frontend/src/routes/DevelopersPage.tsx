// frontend/src/routes/DevelopersPage.tsx
import React, { useState } from 'react';
import { Plus, AlertCircle } from 'lucide-react';
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
    <div className="flex flex-col gap-5 max-w-5xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-slate-200 dark:border-dark-800">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight">
            API Keys
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Use Bearer keys to authenticate requests to <code className="font-mono text-slate-700 dark:text-slate-300">POST /recommend</code>. Keys are limited to 20 requests/minute and expire after 90 days.
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
        <div className="p-3.5 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg text-xs text-red-700 dark:text-red-300 flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Quota Bar */}
      <KeyQuotaBanner activeCount={activeKeysCount} maxAllowed={5} />

      {/* Main Keys Table */}
      <KeyListTable
        keys={keys}
        isLoading={isLoading}
        onRevokeClick={(keyItem) => setRevokeTarget(keyItem)}
      />

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
