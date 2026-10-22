// frontend/src/hooks/useUserPreferences.ts
import { useState, useEffect, useCallback } from 'react';
import type { UserPreferences } from '../types/chat';

const STORAGE_KEY = 'anime_user_preferences_v1';
const EVENT_KEY = 'anime-user-preferences-changed';

const DEFAULT_PREFERENCES: UserPreferences = {
  seen_ids: [],
  disliked_genres: [],
  allow_adult: false,
};

function loadStoredPreferences(): UserPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFERENCES;
    const parsed = JSON.parse(raw);
    return {
      seen_ids: Array.isArray(parsed.seen_ids) ? parsed.seen_ids : [],
      disliked_genres: Array.isArray(parsed.disliked_genres) ? parsed.disliked_genres : [],
      allow_adult: Boolean(parsed.allow_adult),
    };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

function savePreferences(prefs: UserPreferences): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    window.dispatchEvent(new CustomEvent(EVENT_KEY, { detail: prefs }));
  } catch {
    // Ignore storage quota or access errors in sandbox/private modes
  }
}

export function useUserPreferences() {
  const [preferences, setPreferencesState] = useState<UserPreferences>(loadStoredPreferences);

  useEffect(() => {
    const handleSync = (e: Event) => {
      if (e instanceof CustomEvent && e.detail) {
        setPreferencesState(e.detail);
      } else {
        setPreferencesState(loadStoredPreferences());
      }
    };

    window.addEventListener(EVENT_KEY, handleSync);
    window.addEventListener('storage', handleSync);
    return () => {
      window.removeEventListener(EVENT_KEY, handleSync);
      window.removeEventListener('storage', handleSync);
    };
  }, []);

  const updatePreferences = useCallback((updater: (prev: UserPreferences) => UserPreferences) => {
    setPreferencesState((prev) => {
      const next = updater(prev);
      savePreferences(next);
      return next;
    });
  }, []);

  const isSeen = useCallback((id: number): boolean => {
    return preferences.seen_ids.includes(id);
  }, [preferences.seen_ids]);

  const toggleSeen = useCallback((id: number): void => {
    updatePreferences((prev) => {
      const exists = prev.seen_ids.includes(id);
      return {
        ...prev,
        seen_ids: exists
          ? prev.seen_ids.filter((i) => i !== id)
          : [...prev.seen_ids, id],
      };
    });
  }, [updatePreferences]);

  const markSeen = useCallback((id: number): void => {
    updatePreferences((prev) => {
      if (prev.seen_ids.includes(id)) return prev;
      return {
        ...prev,
        seen_ids: [...prev.seen_ids, id],
      };
    });
  }, [updatePreferences]);

  const unmarkSeen = useCallback((id: number): void => {
    updatePreferences((prev) => ({
      ...prev,
      seen_ids: prev.seen_ids.filter((i) => i !== id),
    }));
  }, [updatePreferences]);

  const clearSeen = useCallback((): void => {
    updatePreferences((prev) => ({
      ...prev,
      seen_ids: [],
    }));
  }, [updatePreferences]);

  const isGenreDisliked = useCallback((genre: string): boolean => {
    const norm = genre.trim().toLowerCase();
    return preferences.disliked_genres.some((g) => g.trim().toLowerCase() === norm);
  }, [preferences.disliked_genres]);

  const toggleDislikedGenre = useCallback((genre: string): void => {
    const norm = genre.trim();
    if (!norm) return;
    updatePreferences((prev) => {
      const exists = prev.disliked_genres.some((g) => g.toLowerCase() === norm.toLowerCase());
      return {
        ...prev,
        disliked_genres: exists
          ? prev.disliked_genres.filter((g) => g.toLowerCase() !== norm.toLowerCase())
          : [...prev.disliked_genres, norm],
      };
    });
  }, [updatePreferences]);

  const removeDislikedGenre = useCallback((genre: string): void => {
    const norm = genre.trim().toLowerCase();
    updatePreferences((prev) => ({
      ...prev,
      disliked_genres: prev.disliked_genres.filter((g) => g.trim().toLowerCase() !== norm),
    }));
  }, [updatePreferences]);

  const clearDislikedGenres = useCallback((): void => {
    updatePreferences((prev) => ({
      ...prev,
      disliked_genres: [],
    }));
  }, [updatePreferences]);

  const setAllowAdult = useCallback((allow: boolean): void => {
    updatePreferences((prev) => ({
      ...prev,
      allow_adult: allow,
    }));
  }, [updatePreferences]);

  const resetPreferences = useCallback((): void => {
    updatePreferences(() => ({ ...DEFAULT_PREFERENCES }));
  }, [updatePreferences]);

  return {
    preferences,
    seenCount: preferences.seen_ids.length,
    dislikedGenresCount: preferences.disliked_genres.length,
    isSeen,
    toggleSeen,
    markSeen,
    unmarkSeen,
    clearSeen,
    isGenreDisliked,
    toggleDislikedGenre,
    removeDislikedGenre,
    clearDislikedGenres,
    setAllowAdult,
    resetPreferences,
  };
}
