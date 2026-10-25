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
import { render, screen, fireEvent, act } from '@testing-library/react';
import { AnimeCard } from './AnimeCard';
import * as chatStreamModule from '../../lib/chatStream';
import type { AnimeCandidate } from '../../types/chat';

vi.mock('../../lib/chatStream', () => ({
  streamSinglePitch: vi.fn(),
}));

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

  it('safely renders studios whether provided as strings or nested objects', () => {
    /**
     * Verifies that AnimeCard safely extracts studio names from both primitive strings
     * and AniList nested object structures without throwing React child errors.
     */
    // Scenario 1: Primitive string array
    const animeWithStringStudio: AnimeCandidate = {
      id: 50,
      title_english: 'Hunter x Hunter',
      studios: ['Madhouse'],
    };
    const { unmount: unmount1 } = render(
      <AnimeCard anime={animeWithStringStudio} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('by Madhouse')).toBeInTheDocument();
    unmount1();

    // Scenario 2: AniList nested object structure with node.name
    const animeWithNestedObjectStudio: AnimeCandidate = {
      id: 51,
      title_english: 'Cowboy Bebop',
      studios: [
        {
          id: 1,
          isMain: true,
          node: {
            id: 14,
            name: 'Sunrise',
            isAnimationStudio: true,
          },
        },
      ],
    };
    const { unmount: unmount2 } = render(
      <AnimeCard anime={animeWithNestedObjectStudio} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('by Sunrise')).toBeInTheDocument();
    unmount2();

    // Scenario 3: Object structure with direct name field
    const animeWithDirectObjectStudio: AnimeCandidate = {
      id: 52,
      title_english: 'Violet Evergarden',
      studios: [{ name: 'Kyoto Animation' }],
    };
    const { unmount: unmount3 } = render(
      <AnimeCard anime={animeWithDirectObjectStudio} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText('by Kyoto Animation')).toBeInTheDocument();
    unmount3();

    // Scenario 4: Empty or invalid studio entries
    const animeWithEmptyStudio: AnimeCandidate = {
      id: 53,
      title_english: 'Unknown Studio Anime',
      studios: [{} as any, ''],
    };
    render(
      <AnimeCard anime={animeWithEmptyStudio} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.queryByText(/^by /i)).not.toBeInTheDocument();
  });

  it('sets referrerPolicy to no-referrer on cover image', () => {
    /**
     * Verifies that cover image elements include referrerPolicy="no-referrer"
     * to prevent third-party image CDNs from rejecting requests.
     */
    const anime: AnimeCandidate = {
      id: 60,
      title_english: 'Frieren',
      coverImage_large: 'https://images.anilist.co/frieren.jpg',
    };
    render(<AnimeCard anime={anime} onMoreLikeThis={mockOnMoreLikeThis} />);
    const img = screen.getByRole('img', { name: 'Frieren' });
    expect(img).toHaveAttribute('referrerPolicy', 'no-referrer');
  });

  it('defensively coerces release year and episode counts to integers', () => {
    /**
     * Verifies that decimal numeric strings or floats for release year and episodes
     * are cleanly coerced into rounded integers.
     */
    const anime: AnimeCandidate = {
      id: 61,
      title_english: 'Hunter x Hunter 2011',
      seasonYear: 2011.0 as any,
      season: 'FALL',
      episodes: 148.0 as any,
    };
    const { unmount } = render(
      <AnimeCard anime={anime} onMoreLikeThis={mockOnMoreLikeThis} />
    );
    expect(screen.getByText(/fall 2011/i)).toBeInTheDocument();
    expect(screen.getByText('148 eps')).toBeInTheDocument();
    unmount();

    // Single episode check (1 ep)
    const singleEpAnime: AnimeCandidate = {
      id: 62,
      title_english: 'Akira',
      episodes: 1.0 as any,
    };
    render(<AnimeCard anime={singleEpAnime} onMoreLikeThis={mockOnMoreLikeThis} />);
    expect(screen.getByText('1 ep')).toBeInTheDocument();
  });

  it('renders star prefix and AniList Community Rating tooltip on score badge', () => {
    /**
     * Verifies that the score badge displays a star prefix and explicit tooltip.
     */
    const anime: AnimeCandidate = {
      id: 63,
      title_english: 'Mob Psycho 100',
      averageScore: 86.4,
    };
    render(<AnimeCard anime={anime} onMoreLikeThis={mockOnMoreLikeThis} />);
    const badgeText = screen.getByText('★ 8.6');
    expect(badgeText).toBeInTheDocument();

    const badgeContainer = badgeText.closest('div[title]');
    expect(badgeContainer).toHaveAttribute('title', 'AniList Community Rating: 8.6 / 10');
  });

  it('toggles curator note panel and displays custom note or fallback with exclusion badge', async () => {
    /**
     * Verifies that the curator note button toggles the expanded panel,
     * showing custom curator notes, synthesised notes, and exclusion badges.
     */
    // Scenario 1: Custom curator note and exclusion badge
    const customAnime: AnimeCandidate = {
      id: 64,
      title_english: 'Vinland Saga',
      curator_note: 'Hand-picked for exceptional historical grit.',
      exclusion_badge: 'Avoids Fantasy Tropes',
      genres: ['Action', 'Adventure', 'Drama'],
      averageScore: 88,
    };
    const { unmount } = render(
      <AnimeCard anime={customAnime} onMoreLikeThis={mockOnMoreLikeThis} />
    );

    const curatorBtn = screen.getByRole('button', { name: /curator note ▾/i });
    expect(curatorBtn).toBeInTheDocument();
    expect(screen.queryByText('Hand-picked for exceptional historical grit.')).not.toBeInTheDocument();

    // Click to expand
    fireEvent.click(curatorBtn);
    expect(screen.getByRole('button', { name: /curator note ▴/i })).toBeInTheDocument();
    expect(screen.getByText('Hand-picked for exceptional historical grit.')).toBeInTheDocument();
    expect(screen.getByText('Avoids Fantasy Tropes')).toBeInTheDocument();

    // Click to collapse
    fireEvent.click(screen.getByRole('button', { name: /curator note ▴/i }));
    expect(screen.queryByText('Hand-picked for exceptional historical grit.')).not.toBeInTheDocument();
    unmount();

    // Scenario 2: Synthesised fallback micro-note with skeleton loader during streaming
    let resolvePitchStream: (() => void) | null = null;
    vi.mocked(chatStreamModule.streamSinglePitch).mockImplementation(
      ({ onError }) =>
        new Promise<void>((resolve) => {
          resolvePitchStream = () => {
            onError?.(new Error('offline'));
            resolve();
          };
        })
    );

    const fallbackAnime: AnimeCandidate = {
      id: 65,
      title_english: 'Bocchi the Rock!',
      genres: ['Comedy', 'Music', 'Slice of Life'],
      averageScore: 87,
    };
    render(<AnimeCard anime={fallbackAnime} onMoreLikeThis={mockOnMoreLikeThis} />);
    const fallbackBtn = screen.getByRole('button', { name: /curator note ▾/i });
    fireEvent.click(fallbackBtn);

    // Verifies skeleton loader is rendered while streaming instead of flashing static text
    expect(screen.getByText('Curator synthesising tailored note...')).toBeInTheDocument();

    // Conclude the stream with error/offline fallback
    await act(async () => {
      resolvePitchStream?.();
    });

    // Verifies fallback rationale renders once streaming concludes
    expect(
      screen.getByText(
        'Curator Note: Ranked among top matches. Features Comedy, Music, Slice of Life with an acclaimed 87% AniList community rating.'
      )
    ).toBeInTheDocument();
  });
});
