// frontend/src/components/chat/ConciergePitch.test.tsx
/**
 * Unit tests for ConciergePitch component: markdown rendering, citation chips, and spoiler click-to-reveal toggles.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Fast, isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConciergePitch } from './ConciergePitch';
import type { AnimeCandidate } from '../../types/chat';

describe('ConciergePitch component', () => {
  const sampleCandidates: AnimeCandidate[] = [
    {
      id: 5114,
      title_english: 'Fullmetal Alchemist: Brotherhood',
      title_userPreferred: 'Fullmetal Alchemist: Brotherhood',
    },
    {
      id: 9253,
      title_english: 'Steins;Gate',
      title_userPreferred: 'Steins;Gate',
    },
  ];

  it('renders markdown paragraphs, bullet lists, and bold text formatting', () => {
    /**
     * Verifies that markdown structures (paragraphs, list items, and bold inline spans)
     * are parsed and rendered as semantic HTML elements.
     */
    const pitchText =
      'Here is your curated recommendation:\n\n' +
      '* **Steins;Gate** offers brilliant sci-fi suspense.\n' +
      '* **Fullmetal Alchemist** delivers an epic emotional journey.\n\n' +
      'Enjoy your watch!';

    render(<ConciergePitch text={pitchText} candidates={sampleCandidates} />);

    expect(screen.getByText(/Here is your curated recommendation:/i)).toBeInTheDocument();
    expect(screen.getByText(/Enjoy your watch!/i)).toBeInTheDocument();

    // Bold elements
    const boldSteins = screen.getByText('Steins;Gate');
    expect(boldSteins.tagName).toBe('STRONG');

    const boldFMA = screen.getByText('Fullmetal Alchemist');
    expect(boldFMA.tagName).toBe('STRONG');
  });

  it('parses structured citation chips and resolves candidate titles', () => {
    /**
     * Verifies that [[anime:<id>]] tokens are converted into interactive citation chips
     * showing the matching candidate title, and falling back gracefully for unknown IDs.
     */
    const onSelectAnime = vi.fn();
    const onHoverAnime = vi.fn();

    const pitchText =
      'If you love philosophical mysteries, start with [[anime:5114]] or explore [[anime:9999]].';

    render(
      <ConciergePitch
        text={pitchText}
        candidates={sampleCandidates}
        onSelectAnime={onSelectAnime}
        onHoverAnime={onHoverAnime}
      />
    );

    // Resolved title for known ID 5114
    const fmaChip = screen.getByRole('button', { name: /fullmetal alchemist: brotherhood/i });
    expect(fmaChip).toBeInTheDocument();
    expect(fmaChip).toHaveAttribute('title', 'Jump to Fullmetal Alchemist: Brotherhood');

    // Fallback title for unknown ID 9999
    const unknownChip = screen.getByRole('button', { name: /anime #9999/i });
    expect(unknownChip).toBeInTheDocument();
    expect(unknownChip).toHaveAttribute('title', 'Jump to Anime #9999');

    // Click on known chip
    fireEvent.click(fmaChip);
    expect(onSelectAnime).toHaveBeenCalledTimes(1);
    expect(onSelectAnime).toHaveBeenCalledWith(5114);

    // Hover on known chip
    fireEvent.mouseEnter(fmaChip);
    expect(onHoverAnime).toHaveBeenCalledWith(5114);

    fireEvent.mouseLeave(fmaChip);
    expect(onHoverAnime).toHaveBeenCalledWith(null);
  });

  it('toggles scrubbed spoilers between redacted state and revealed state on click', () => {
    /**
     * Verifies that safety-scrubbed [spoiler redacted] badges start hidden and
     * reveal safe disclaimer text when clicked, toggling back on subsequent clicks.
     */
    const pitchText = 'Be careful because at the end of the show [spoiler redacted]!';

    render(<ConciergePitch text={pitchText} />);

    // Initially redacted
    const spoilerBtn = screen.getByRole('button', { name: /spoiler redacted/i });
    expect(spoilerBtn).toBeInTheDocument();
    expect(spoilerBtn).toHaveAttribute('title', 'Click to reveal spoiler');

    // Click to reveal
    fireEvent.click(spoilerBtn);
    expect(screen.getByText(/plot twist redacted for safety/i)).toBeInTheDocument();

    // Click to hide again
    const hideBtn = screen.getByRole('button', { name: /plot twist redacted/i });
    expect(hideBtn).toHaveAttribute('title', 'Click to hide spoiler');
    fireEvent.click(hideBtn);
    expect(screen.getByRole('button', { name: /spoiler redacted/i })).toBeInTheDocument();
  });

  it('toggles inline pipe spoilers to reveal hidden plot content on click', () => {
    /**
     * Verifies that ||hidden content|| syntax is masked initially and reveals
     * the actual hidden content upon user interaction.
     */
    const pitchText = 'The killer was ||the high school teacher|| all along.';

    render(<ConciergePitch text={pitchText} />);

    // Content should not be visible initially
    expect(screen.queryByText('the high school teacher')).not.toBeInTheDocument();

    const spoilerBtn = screen.getByRole('button', { name: /spoiler redacted/i });
    fireEvent.click(spoilerBtn);

    // Hidden content is now revealed
    expect(screen.getByText('the high school teacher')).toBeInTheDocument();

    // Click to re-hide
    const hideBtn = screen.getByRole('button', { name: /the high school teacher/i });
    expect(hideBtn).toHaveAttribute('title', 'Click to hide spoiler');
    fireEvent.click(hideBtn);
    expect(screen.queryByText('the high school teacher')).not.toBeInTheDocument();
  });

  it('renders streaming state indicator while content is being generated', () => {
    /**
     * Verifies that isStreaming=true renders the streaming AI commentary badge.
     */
    render(<ConciergePitch text="Partial stream..." isStreaming={true} />);

    expect(screen.getByText(/streaming ai commentary/i)).toBeInTheDocument();
    expect(screen.getByLabelText('cursor')).toBeInTheDocument();
  });
});
