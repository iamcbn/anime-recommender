// frontend/src/components/developers/KeyListTable.tsx
import React from 'react';
import { Trash2, Clock, AlertOctagon } from 'lucide-react';
import type { KeyItem } from '../../types/apiKeys';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';

export interface KeyListTableProps {
  keys: KeyItem[];
  isLoading: boolean;
  onRevokeClick: (keyItem: KeyItem) => void;
}

export const KeyListTable: React.FC<KeyListTableProps> = ({
  keys,
  isLoading,
  onRevokeClick,
}) => {
  const formatDate = (isoStr: string | null) => {
    if (!isoStr) return 'Never';
    const date = new Date(isoStr);
    return date.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getKeyStatus = (keyItem: KeyItem): { label: string; variant: 'success' | 'danger' | 'warning' } => {
    if (keyItem.revoked_at) {
      return { label: 'Revoked', variant: 'danger' };
    }
    if (keyItem.expires_at && new Date(keyItem.expires_at) <= new Date()) {
      return { label: 'Expired', variant: 'warning' };
    }
    return { label: 'Active', variant: 'success' };
  };

  if (isLoading && keys.length === 0) {
    return (
      <div className="w-full py-12 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 gap-3">
        <Clock className="w-6 h-6 animate-spin text-brand" />
        <span className="text-sm">Loading your developer keys...</span>
      </div>
    );
  }

  if (keys.length === 0) {
    return (
      <div className="w-full py-16 flex flex-col items-center justify-center text-center p-6 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-xl shadow-sm">
        <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-dark-800 flex items-center justify-center text-slate-400 mb-3">
          <AlertOctagon className="w-6 h-6" />
        </div>
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">No API Keys Yet</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mt-1 mb-4">
          Generate an API key to access the Anime Recommender recommendation and semantic search endpoints.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full overflow-x-auto rounded-xl border border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 shadow-sm">
      <table className="w-full text-left text-sm text-slate-700 dark:text-slate-300">
        <thead className="bg-slate-50 dark:bg-dark-950 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-dark-800">
          <tr>
            <th className="px-5 py-3.5">Name</th>
            <th className="px-5 py-3.5">Key Prefix</th>
            <th className="px-5 py-3.5">Created</th>
            <th className="px-5 py-3.5">Last Used</th>
            <th className="px-5 py-3.5">Status</th>
            <th className="px-5 py-3.5 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 dark:divide-dark-800 text-xs">
          {keys.map((k) => {
            const status = getKeyStatus(k);
            const isInactive = Boolean(k.revoked_at || (k.expires_at && new Date(k.expires_at) <= new Date()));

            return (
              <tr key={k.id} className="hover:bg-slate-50 dark:hover:bg-dark-800/50 transition-colors">
                <td className="px-5 py-4 font-medium text-slate-900 dark:text-white max-w-[200px] truncate">
                  {k.name}
                </td>
                <td className="px-5 py-4 font-mono text-slate-500 dark:text-slate-400">
                  <span className="text-indigo-600 dark:text-indigo-400 font-semibold">{k.prefix}</span>
                  <span className="opacity-40">••••••••••••••••</span>
                </td>
                <td className="px-5 py-4 text-slate-500 dark:text-slate-400">{formatDate(k.created_at)}</td>
                <td className="px-5 py-4 text-slate-500 dark:text-slate-400">{formatDate(k.last_used_at)}</td>
                <td className="px-5 py-4">
                  <Badge variant={status.variant} size="sm">
                    {status.label}
                  </Badge>
                </td>
                <td className="px-5 py-4 text-right">
                  {!isInactive ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onRevokeClick(k)}
                      className="text-slate-500 hover:text-red-600 hover:bg-red-50 dark:text-slate-400 dark:hover:text-red-400 dark:hover:bg-red-500/10"
                      title="Revoke key"
                      icon={<Trash2 className="w-3.5 h-3.5" />}
                    >
                      Revoke
                    </Button>
                  ) : (
                    <span className="text-xs text-slate-400 dark:text-slate-600 italic">No actions</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
