// frontend/src/components/developers/RevokeKeyModal.tsx
import React, { useState } from 'react';
import { AlertTriangle, Trash2 } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import type { KeyItem } from '../../types/apiKeys';

export interface RevokeKeyModalProps {
  keyItem: KeyItem | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (keyId: string) => Promise<void>;
}

export const RevokeKeyModal: React.FC<RevokeKeyModalProps> = ({
  keyItem,
  isOpen,
  onClose,
  onConfirm,
}) => {
  const [isRevoking, setIsRevoking] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  if (!keyItem) return null;

  const handleRevoke = async () => {
    setIsRevoking(true);
    setError(null);
    try {
      await onConfirm(keyItem.id);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to revoke key';
      setError(msg);
    } finally {
      setIsRevoking(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Revoke API Key"
      description="This action cannot be undone. Any application relying on this key will lose access immediately."
      maxWidth="sm"
    >
      <div className="flex flex-col gap-4">
        <div className="p-3 bg-red-50 border border-red-200 text-red-800 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300 rounded-lg text-xs flex items-start gap-2.5">
          <AlertTriangle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0 mt-0.5" />
          <div>
            Revoking key: <span className="font-semibold text-slate-900 dark:text-white">{keyItem.name}</span>
            <div className="font-mono text-slate-500 dark:text-slate-400 mt-0.5">{keyItem.prefix}••••••••</div>
          </div>
        </div>

        {error && (
          <p className="text-xs text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/40 p-2.5 rounded-lg border border-red-200 dark:border-red-800">
            {error}
          </p>
        )}

        <div className="flex items-center justify-end gap-2 mt-2">
          <Button variant="ghost" onClick={onClose} disabled={isRevoking}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={handleRevoke}
            isLoading={isRevoking}
            icon={<Trash2 className="w-4 h-4" />}
          >
            Revoke Key
          </Button>
        </div>
      </div>
    </Modal>
  );
};
