// frontend/src/hooks/useApiKeys.ts
import { useState, useEffect, useCallback, useMemo } from 'react';
import { devKeysApi, ApiClientError } from '../lib/apiClient';
import type { KeyItem, CreateKeyResponse } from '../types/apiKeys';
import { useAuth } from './useAuth';

export const useApiKeys = () => {
  const { session } = useAuth();
  const [keys, setKeys] = useState<KeyItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchKeys = useCallback(async () => {
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await devKeysApi.listKeys();
      setKeys(response.keys || []);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load API keys');
      }
    } finally {
      setIsLoading(false);
    }
  }, [session]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const activeKeysCount = useMemo(() => {
    const now = new Date();
    return keys.filter((key) => {
      if (key.revoked_at) return false;
      if (key.expires_at && new Date(key.expires_at) <= now) return false;
      return true;
    }).length;
  }, [keys]);

  const isAtMaxLimit = activeKeysCount >= 5;

  const createKey = async (name: string): Promise<CreateKeyResponse> => {
    setError(null);
    try {
      const res = await devKeysApi.createKey(name);
      await fetchKeys();
      return res;
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
        throw err;
      }
      const genericError = new ApiClientError(500, 'create_failed', 'Failed to create API key');
      setError(genericError.message);
      throw genericError;
    }
  };

  const revokeKey = async (keyId: string): Promise<void> => {
    setError(null);
    try {
      await devKeysApi.revokeKey(keyId);
      // Optimistic update
      setKeys((prev) =>
        prev.map((k) =>
          k.id === keyId ? { ...k, revoked_at: new Date().toISOString() } : k
        )
      );
      await fetchKeys();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
        throw err;
      }
      const genericError = new ApiClientError(500, 'revoke_failed', 'Failed to revoke API key');
      setError(genericError.message);
      throw genericError;
    }
  };

  return {
    keys,
    isLoading,
    error,
    activeKeysCount,
    isAtMaxLimit,
    fetchKeys,
    createKey,
    revokeKey,
  };
};
