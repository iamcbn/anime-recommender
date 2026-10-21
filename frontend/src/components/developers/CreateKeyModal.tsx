// frontend/src/components/developers/CreateKeyModal.tsx
import React, { useState, useEffect } from 'react';
import { Key, Copy, Check, AlertTriangle, ShieldCheck } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { useClipboard } from '../../hooks/useClipboard';
import type { CreateKeyResponse } from '../../types/apiKeys';

export interface CreateKeyModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<CreateKeyResponse>;
  isAtLimit: boolean;
}

export const CreateKeyModal: React.FC<CreateKeyModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  isAtLimit,
}) => {
  const [name, setName] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [createdKeyData, setCreatedKeyData] = useState<CreateKeyResponse | null>(null);
  const [hasAcknowledged, setHasAcknowledged] = useState<boolean>(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const { copied, copy } = useClipboard(3000);

  // Security Invariant: Clean up transient key state when modal unmounts or closes
  useEffect(() => {
    return () => {
      setCreatedKeyData(null);
      setName('');
      setHasAcknowledged(false);
      setValidationError(null);
    };
  }, [isOpen]);

  const handleClose = () => {
    // Explicitly zero out key state upon dismissal
    setCreatedKeyData(null);
    setName('');
    setHasAcknowledged(false);
    setValidationError(null);
    onClose();
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setValidationError('Key name is required.');
      return;
    }
    if (trimmed.length > 64) {
      setValidationError('Key name cannot exceed 64 characters.');
      return;
    }
    if (!/^[a-zA-Z0-9_\-\s]+$/.test(trimmed)) {
      setValidationError('Key name can only contain letters, numbers, hyphens, underscores, and spaces.');
      return;
    }

    setValidationError(null);
    setIsSubmitting(true);
    try {
      const res = await onSubmit(trimmed);
      setCreatedKeyData(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create key';
      setValidationError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={createdKeyData ? 'Save Your API Key' : 'Create API Key'}
      description={
        createdKeyData
          ? 'Copy this key now and store it in your server environment. It will not be shown again.'
          : 'Enter a name to identify this key in your account.'
      }
      locked={Boolean(createdKeyData && !hasAcknowledged)}
      maxWidth="md"
    >
      {!createdKeyData ? (
        <form onSubmit={handleGenerate} className="flex flex-col gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              Key Name / Description
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setValidationError(null);
              }}
              placeholder="e.g. production-backend, eval-runner"
              className="w-full px-3.5 py-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent text-sm font-sans"
              maxLength={64}
              disabled={isSubmitting || isAtLimit}
              autoFocus
            />
            {validationError && (
              <p className="text-xs text-red-600 dark:text-red-400 mt-1.5 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                {validationError}
              </p>
            )}
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1.5">
              Default quota: 20 req/min. Key automatically expires after 90 days.
            </p>
          </div>

          <div className="flex items-center justify-end gap-2 mt-2">
            <Button variant="ghost" onClick={handleClose} type="button" disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting}
              disabled={!name.trim() || isAtLimit}
              icon={<Key className="w-4 h-4" />}
            >
              Generate Key
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs text-amber-800 dark:text-amber-300 flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
            <span>
              This secret key will <strong>never be shown again</strong>. Store it securely in your
              server environment variables (e.g. <code className="bg-amber-500/20 px-1 py-0.5 rounded">ANIME_API_KEY</code>).
              Never commit it or expose it in client-side web apps.
            </span>
          </div>

          {/* Key Display & Copy Box */}
          <div className="relative flex items-center justify-between p-3 bg-slate-100 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 rounded-lg font-mono text-xs text-indigo-700 dark:text-brand-light break-all select-all">
            <span className="pr-10">{createdKeyData.key}</span>
            <button
              onClick={() => copy(createdKeyData.key)}
              className="absolute right-2 top-2 p-1.5 rounded-md bg-white hover:bg-slate-200 dark:bg-dark-800 dark:hover:bg-dark-700 text-slate-700 dark:text-slate-300 shadow-sm transition-colors border border-slate-200 dark:border-transparent"
              title="Copy API key"
            >
              {copied ? (
                <Check className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Acknowledgement Gate */}
          <label className="flex items-start gap-2.5 cursor-pointer text-xs text-slate-700 dark:text-slate-300 select-none mt-1">
            <input
              type="checkbox"
              checked={hasAcknowledged}
              onChange={(e) => setHasAcknowledged(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded bg-white dark:bg-dark-950 border-slate-300 dark:border-dark-700 text-brand focus:ring-brand focus:ring-offset-white dark:focus:ring-offset-dark-900"
            />
            <span>
              I have safely copied and stored this secret key. I understand it cannot be displayed
              again.
            </span>
          </label>

          <div className="flex items-center justify-end gap-2 mt-3">
            <Button
              variant="primary"
              onClick={handleClose}
              disabled={!hasAcknowledged}
              icon={<ShieldCheck className="w-4 h-4" />}
            >
              I&apos;ve Saved My Key
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
};
