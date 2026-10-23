// frontend/src/components/chat/AnimeCard.test.tsx
/**
 * Unit tests for AnimeCard component: title resolution hierarchy, format badge, synopsis expansion, and seen toggling.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Fast, isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AnimeCard } from './AnimeCard';
import type { AnimeCandidate } from '../../types/chat';

describe('AnimeCard component', () => {
  const mockOnMoreLikeThis = vi.fn();

  beforeEach(() => {
    localStorage.clear();
    mockOnMoreLikeThis.mockClear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('resolves title hierarchy prioritising userPreferred, then english, then romaji', () => {
    /**
     * Verifies that AnimeCard adheres strictly to the title resolution hierarchy:
     * title_userPreferred -> title_english -> title_romaji -> 'Untitled Anime'.
     */
    // Scenario 1: userPreferred provided
    const animeWithUserPreferred: AnimeCandidate = {
      id: 1,
      title_userPreferred: 'Attack on Titan Preferred',
      title_english: 'Attack on Titan English',
      title_romaji: 'Shingeki no Kyojin Romaji',
    };
    const { unmount: unmount1 } = render(
      <AnimeCard anime={animeWithUserPreferred} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('Attack on Titan Preferred')).toBeInTheDocument();
    unmount1();

    // Scenario 2: english provided, no userPreferred
    const animeWithEnglishOnly: AnimeCandidate = {
      id: 2,
      title_english: 'Fullmetal Alchemist English',
      title_romaji: 'Hagane no Renkinjutsushi Romaji',
    };
    const { unmount: unmount2 } = render(
      <AnimeCard anime={animeWithEnglishOnly} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('Fullmetal Alchemist English')).toBeInTheDocument();
    unmount2();

    // Scenario 3: romaji provided, no userPreferred or english
    const animeWithRomajiOnly: AnimeCandidate = {
      id: 3,
      title_romaji: 'Steins;Gate Romaji',
    };
    const { unmount: unmount3 } = render(
      <AnimeCard anime={animeWithRomajiOnly} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('Steins;Gate Romaji')).toBeInTheDocument();
    unmount3();

    // Scenario 4: no titles provided
    const animeWithoutTitle: AnimeCandidate = {
      id: 4,
    };
    const { unmount: unmount4 } = render(
      <AnimeCard anime={animeWithoutTitle} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('Untitled Anime')).toBeInTheDocument();
    unmount4();
  });

  it('renders format badge in uppercase format with TV fallback', () => {
    /**
     * Verifies that AnimeCard displays media formats (e.g. MOVIE, OVA, TV)
     * uppercase and falls back to TV if unspecified.
     */
    const movieAnime: AnimeCandidate = {
      id: 10,
      title_english: 'Your Name',
      format: 'movie',
    };
    const { unmount } = render(
      <AnimeCard anime={movieAnime} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getAllByText('MOVIE').length).toBeGreaterThan(0);
    unmount();

    const unspecifiedAnime: AnimeCandidate = {
      id: 11,
      title_english: 'Cowboy Bebop',
    };
    render(
      <AnimeCard anime={unspecifiedAnime} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getAllByText('TV').length).toBeGreaterThan(0);
  });

  it('truncates long synopses and expands upon clicking Read more', () => {
    /**
     * Verifies that synopses longer than 170 characters are truncated with an ellipsis
     * and an interactive Read more button that expands the complete synopsis.
     */
    const longSynopsis =
      'A thrilling psychological battle between two masterminds where a young student ' +
      'discovers a supernatural notebook that can eliminate anyone whose name is written inside it, ' +
      'prompting an international detective manhunt.';

    const anime: AnimeCandidate = {
      id: 20,
      title_english: 'Death Note',
      synopsis: longSynopsis,
    };

    render(<AnimeCard anime={anime} onMoreLikeThis={mockOnMoreLikeThis} />);

    // Read more button should be present
    const readMoreBtn = screen.getByRole('button', { name: /read more/i });
    expect(readMoreBtn).toBeInTheDocument();

    // Click to expand
    fireEvent.click(readMoreBtn);

    // Button text switches to Less
    expect(screen.getByRole('button', { name: /less/i })).toBeInTheDocument();
    expect(screen.getByText(longSynopsis)).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(screen.getByRole('button', { name: /less/i }));
    expect(screen.getByRole('button', { name: /read more/i })).toBeInTheDocument();
  });

  it('toggles seen status and displays visual seen badge when clicked', () => {
    /**
     * Verifies that clicking Mark as seen toggles preference state, shows the Seen badge,
     * and updates the button label to Seen it.
     */
    const anime: AnimeCandidate = {
      id: 30,
      title_english: 'Monster',
    };

    render(<AnimeCard anime={anime} onMoreLikeThis={mockOnMoreLikeThis} />);

    const seenButton = screen.getByRole('button', { name: /mark as seen/i });
    expect(seenButton).toBeInTheDocument();

    // Click to mark as seen
    fireEvent.click(seenButton);

    // Expect Seen badge indicator and updated button label
    expect(screen.getByRole('button', { name: /seen it/i })).toBeInTheDocument();
    expect(screen.getByText('Seen')).toBeInTheDocument();

    // Click again to unmark
    fireEvent.click(screen.getByRole('button', { name: /seen it/i }));
    expect(screen.getByRole('button', { name: /mark as seen/i })).toBeInTheDocument();
  });

  it('triggers onMoreLikeThis callback with resolved title when clicked', () => {
    /**
     * Verifies that clicking More like this invokes the callback with the canonical title.
     */
    const anime: AnimeCandidate = {
      id: 40,
      title_english: 'Code Geass',
    };

    render(<AnimeCard anime={anime} onMoreLikeThis={mockOnMoreLikeThis} />);

    const moreBtn = screen.getByRole('button', { name: /more like this/i });
    fireEvent.click(moreBtn);

    expect(mockOnMoreLikeThis).toHaveBeenCalledTimes(1);
    expect(mockOnMoreLikeThis).toHaveBeenCalledWith('Code Geass');
  });
});
