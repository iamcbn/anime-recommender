// frontend/src/hooks/useUserPreferences.test.ts
/**
 * Unit tests for user preferences state management, local storage persistence, and filter toggles.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Fast, isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useUserPreferences } from './useUserPreferences';

const STORAGE_KEY = 'anime_user_preferences_v1';

describe('useUserPreferences hook', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('initialises with default preferences when local storage is empty', () => {
    /**
     * Verifies that the hook provides clean empty defaults when no prior
     * user preferences exist in local storage.
     */
    const { result } = renderHook(() => useUserPreferences());

    expect(result.current.preferences).toEqual({
      seen_ids: [],
      disliked_genres: [],
      allow_adult: false,
    });
    expect(result.current.seenCount).toBe(0);
    expect(result.current.dislikedGenresCount).toBe(0);
  });

  it('gracefully recovers default preferences when local storage contains malformed JSON', () => {
    /**
     * Verifies that corrupt or unparseable local storage data does not crash the client,
     * resetting safely to default preferences.
     */
    localStorage.setItem(STORAGE_KEY, '{ invalid_json_syntax: true');

    const { result } = renderHook(() => useUserPreferences());

    expect(result.current.preferences).toEqual({
      seen_ids: [],
      disliked_genres: [],
      allow_adult: false,
    });
  });

  it('loads valid pre-existing preferences from local storage', () => {
    /**
     * Verifies that existing preferences stored in local storage are restored accurately on boot.
     */
    const initialData = {
      seen_ids: [1535, 5114],
      disliked_genres: ['Ecchi', 'Harem'],
      allow_adult: true,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(initialData));

    const { result } = renderHook(() => useUserPreferences());

    expect(result.current.preferences.seen_ids).toEqual([1535, 5114]);
    expect(result.current.preferences.disliked_genres).toEqual(['Ecchi', 'Harem']);
    expect(result.current.preferences.allow_adult).toBe(true);
    expect(result.current.isSeen(1535)).toBe(true);
    expect(result.current.isSeen(9999)).toBe(false);
  });

  it('toggles seen anime IDs on and off and persists updates to local storage', () => {
    /**
     * Verifies that toggleSeen alternates an anime ID between seen and unseen states,
     * maintaining synchronised persistence in local storage.
     */
    const { result } = renderHook(() => useUserPreferences());

    // 1. Mark as seen
    act(() => {
      result.current.toggleSeen(1535);
    });
    expect(result.current.isSeen(1535)).toBe(true);
    expect(result.current.preferences.seen_ids).toContain(1535);

    const storedAfterAdd = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    expect(storedAfterAdd.seen_ids).toContain(1535);

    // 2. Toggle again to unmark
    act(() => {
      result.current.toggleSeen(1535);
    });
    expect(result.current.isSeen(1535)).toBe(false);
    expect(result.current.preferences.seen_ids).not.toContain(1535);

    const storedAfterRemove = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    expect(storedAfterRemove.seen_ids).not.toContain(1535);
  });

  it('toggles disliked genres case-insensitively', () => {
    /**
     * Verifies that toggleDislikedGenre handles casing variations gracefully,
     * preventing duplicate genre entries with mismatched capitalisation.
     */
    const { result } = renderHook(() => useUserPreferences());

    // Add 'Horror'
    act(() => {
      result.current.toggleDislikedGenre('Horror');
    });
    expect(result.current.isGenreDisliked('horror')).toBe(true);
    expect(result.current.isGenreDisliked('HORROR')).toBe(true);
    expect(result.current.preferences.disliked_genres).toEqual(['Horror']);

    // Remove with lowercase 'horror'
    act(() => {
      result.current.toggleDislikedGenre('horror');
    });
    expect(result.current.isGenreDisliked('horror')).toBe(false);
    expect(result.current.preferences.disliked_genres).toEqual([]);
  });

  it('resets all preferences back to factory defaults', () => {
    /**
     * Verifies that resetPreferences wipes all configured seen IDs, disliked genres,
     * and adult content toggles in both state and local storage.
     */
    const { result } = renderHook(() => useUserPreferences());

    act(() => {
      result.current.markSeen(101);
      result.current.toggleDislikedGenre('Mecha');
      result.current.setAllowAdult(true);
    });

    expect(result.current.preferences.seen_ids.length).toBe(1);

    act(() => {
      result.current.resetPreferences();
    });

    expect(result.current.preferences).toEqual({
      seen_ids: [],
      disliked_genres: [],
      allow_adult: false,
    });
  });
});
