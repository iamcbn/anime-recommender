// frontend/src/lib/userPreferences.ts
import type { UserPreferences } from '../types/chat';

export const PREFERENCES_STORAGE_KEY = 'ar_user_preferences_v1';
export const PREFERENCES_CHANGED_EVENT = 'ar:preferences-changed';

export const DEFAULT_USER_PREFERENCES: Readonly<UserPreferences> = Object.freeze({
  seen_ids: [],
  disliked_genres: [],
  allow_adult: false,
});

// In-memory fallback for SSR or environments where localStorage throws/is restricted
let memoryStore: UserPreferences = {
  seen_ids: [],
  disliked_genres: [],
  allow_adult: false,
};

function isStorageAvailable(): boolean {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return false;
  }
  try {
    const testKey = '__ar_storage_test__';
    window.localStorage.setItem(testKey, '1');
    window.localStorage.removeItem(testKey);
    return true;
  } catch {
    return false;
  }
}

function deduplicateNumbers(arr: unknown[]): number[] {
  const set = new Set<number>();
  for (const item of arr) {
    if (typeof item === 'number' && Number.isFinite(item) && item > 0) {
      set.add(Math.floor(item));
    }
  }
  return Array.from(set);
}

function deduplicateStrings(arr: unknown[]): string[] {
  const map = new Map<string, string>();
  for (const item of arr) {
    if (typeof item === 'string') {
      const trimmed = item.trim();
      if (trimmed) {
        const lower = trimmed.toLowerCase();
        if (!map.has(lower)) {
          map.set(lower, trimmed);
        }
      }
    }
  }
  return Array.from(map.values());
}

/**
 * Retrieves user preferences from browser localStorage.
 * Sanitizes and validates data, falling back to defaults if missing or corrupted.
 */
export function getUserPreferences(): UserPreferences {
  if (!isStorageAvailable()) {
    return {
      seen_ids: [...memoryStore.seen_ids],
      disliked_genres: [...memoryStore.disliked_genres],
      allow_adult: memoryStore.allow_adult,
    };
  }

  try {
    const raw = window.localStorage.getItem(PREFERENCES_STORAGE_KEY);
    if (!raw) {
      return {
        seen_ids: [...DEFAULT_USER_PREFERENCES.seen_ids],
        disliked_genres: [...DEFAULT_USER_PREFERENCES.disliked_genres],
        allow_adult: DEFAULT_USER_PREFERENCES.allow_adult,
      };
    }

    const parsed = JSON.parse(raw);
    const seen_ids = Array.isArray(parsed?.seen_ids)
      ? deduplicateNumbers(parsed.seen_ids)
      : [];
    const disliked_genres = Array.isArray(parsed?.disliked_genres)
      ? deduplicateStrings(parsed.disliked_genres)
      : [];
    const allow_adult = Boolean(parsed?.allow_adult);

    return { seen_ids, disliked_genres, allow_adult };
  } catch {
    return {
      seen_ids: [...DEFAULT_USER_PREFERENCES.seen_ids],
      disliked_genres: [...DEFAULT_USER_PREFERENCES.disliked_genres],
      allow_adult: DEFAULT_USER_PREFERENCES.allow_adult,
    };
  }
}

/**
 * Persists updated preferences to localStorage and dispatches `ar:preferences-changed`
 * so all active React components synchronize immediately.
 */
export function saveUserPreferences(updates: Partial<UserPreferences>): UserPreferences {
  const current = getUserPreferences();

  const nextPrefs: UserPreferences = {
    seen_ids:
      updates.seen_ids !== undefined
        ? deduplicateNumbers(updates.seen_ids)
        : current.seen_ids,
    disliked_genres:
      updates.disliked_genres !== undefined
        ? deduplicateStrings(updates.disliked_genres)
        : current.disliked_genres,
    allow_adult:
      updates.allow_adult !== undefined
        ? Boolean(updates.allow_adult)
        : current.allow_adult,
  };

  memoryStore = {
    seen_ids: [...nextPrefs.seen_ids],
    disliked_genres: [...nextPrefs.disliked_genres],
    allow_adult: nextPrefs.allow_adult,
  };

  if (isStorageAvailable()) {
    try {
      window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(nextPrefs));
    } catch (err) {
      console.warn('[UserPreferences] Failed to persist to localStorage:', err);
    }
  }

  if (typeof window !== 'undefined') {
    try {
      window.dispatchEvent(
        new CustomEvent(PREFERENCES_CHANGED_EVENT, { detail: nextPrefs })
      );
    } catch {
      // Ignore if CustomEvent dispatch fails in unsupported environments
    }
  }

  return nextPrefs;
}

/**
 * Marks an anime ID as seen so it will be excluded from subsequent recommendations.
 */
export function markSeen(animeId: number): void {
  if (typeof animeId !== 'number' || !Number.isFinite(animeId) || animeId <= 0) {
    return;
  }
  const current = getUserPreferences();
  if (!current.seen_ids.includes(animeId)) {
    saveUserPreferences({ seen_ids: [...current.seen_ids, animeId] });
  }
}

/**
 * Removes an anime ID from the seen list.
 */
export function unmarkSeen(animeId: number): void {
  if (typeof animeId !== 'number') return;
  const current = getUserPreferences();
  if (current.seen_ids.includes(animeId)) {
    saveUserPreferences({
      seen_ids: current.seen_ids.filter((id) => id !== animeId),
    });
  }
}

/**
 * Checks whether an anime ID is in the user's seen list.
 */
export function isSeen(animeId: number): boolean {
  if (typeof animeId !== 'number') return false;
  return getUserPreferences().seen_ids.includes(animeId);
}

/**
 * Toggles a genre into or out of the disliked genres list (case-insensitive).
 */
export function toggleDislikedGenre(genre: string): void {
  if (typeof genre !== 'string') return;
  const normalized = genre.trim();
  if (!normalized) return;

  const current = getUserPreferences();
  const lower = normalized.toLowerCase();
  const exists = current.disliked_genres.some((g) => g.toLowerCase() === lower);

  if (exists) {
    saveUserPreferences({
      disliked_genres: current.disliked_genres.filter((g) => g.toLowerCase() !== lower),
    });
  } else {
    saveUserPreferences({
      disliked_genres: [...current.disliked_genres, normalized],
    });
  }
}

/**
 * Checks whether a genre is in the disliked list (case-insensitive).
 */
export function isGenreDisliked(genre: string): boolean {
  if (typeof genre !== 'string') return false;
  const lower = genre.trim().toLowerCase();
  if (!lower) return false;
  return getUserPreferences().disliked_genres.some((g) => g.toLowerCase() === lower);
}

/**
 * Configures whether adult (18+) titles should be permitted in chat recommendations.
 */
export function setAllowAdult(allow: boolean): void {
  saveUserPreferences({ allow_adult: Boolean(allow) });
}

/**
 * Clears all watched/seen anime IDs.
 */
export function clearSeen(): void {
  saveUserPreferences({ seen_ids: [] });
}

/**
 * Clears all disliked genres.
 */
export function clearDislikedGenres(): void {
  saveUserPreferences({ disliked_genres: [] });
}

/**
 * Clears all preferences back to initial defaults.
 */
export function clearAllPreferences(): void {
  saveUserPreferences({
    seen_ids: [],
    disliked_genres: [],
    allow_adult: false,
  });
}
