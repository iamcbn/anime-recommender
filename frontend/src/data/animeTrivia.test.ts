// frontend/src/data/animeTrivia.test.ts
import { describe, it, expect } from 'vitest';
import { ANIME_TRIVIA_ITEMS, TriviaCycleManager } from './animeTrivia';

describe('Anime Trivia Dataset & Cycle Manager', () => {
  it('contains exactly 60 deep-cut anime trivia entries', () => {
    expect(ANIME_TRIVIA_ITEMS).toHaveLength(60);
    // Ensure all items are non-empty strings and start with the standard prefix
    ANIME_TRIVIA_ITEMS.forEach((item) => {
      expect(typeof item).toBe('string');
      expect(item.startsWith('Did you know?')).toBe(true);
      expect(item.length).toBeGreaterThan(20);
    });
  });

  it('contains zero em-dashes across all trivia lines', () => {
    ANIME_TRIVIA_ITEMS.forEach((item) => {
      expect(item).not.toContain('\u2014');
      expect(item).not.toContain('—');
    });
  });

  it('cycles through all items before repeating in a shuffle-then-cycle rotation', () => {
    const manager = new TriviaCycleManager(ANIME_TRIVIA_ITEMS);
    const seenItems = new Set<string>();

    // Retrieve all 60 items in the first cycle
    for (let i = 0; i < 60; i++) {
      const item = manager.getNextTrivia();
      expect(seenItems.has(item)).toBe(false);
      seenItems.add(item);
    }

    expect(seenItems.size).toBe(60);

    // 61st item triggers reshuffle and must be a valid item from the dataset
    const nextCycleItem = manager.getNextTrivia();
    expect(ANIME_TRIVIA_ITEMS).toContain(nextCycleItem);
  });

  it('peek returns upcoming item without advancing position', () => {
    const manager = new TriviaCycleManager(['Fact A', 'Fact B']);
    const peeked = manager.peek();
    const next = manager.getNextTrivia();
    expect(peeked).toBe(next);
  });

  it('reset reshuffles and restarts the cycle', () => {
    const manager = new TriviaCycleManager(ANIME_TRIVIA_ITEMS);
    manager.getNextTrivia();
    manager.getNextTrivia();
    manager.reset();
    // After reset, we should be able to retrieve 60 distinct items again
    const seen = new Set<string>();
    for (let i = 0; i < 60; i++) {
      seen.add(manager.getNextTrivia());
    }
    expect(seen.size).toBe(60);
  });
});
