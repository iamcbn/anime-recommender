// frontend/src/routes/ChatPage.test.tsx
/**
 * Unit tests for ChatPage conversational message feed, turn progression, and candidate mounting.
 *
 * Conforms to clean code rules:
 * - Isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ChatPage } from './ChatPage';
import * as chatStreamModule from '../lib/chatStream';
import type { AnimeCandidate } from '../types/chat';

vi.mock('../lib/chatStream', () => ({
  streamChat: vi.fn(),
}));

describe('ChatPage Conversational Message Feed', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    localStorage.clear();
  });

  const sampleCandidate: AnimeCandidate = {
    id: 1,
    title_userPreferred: 'Cowboy Bebop',
    title_english: 'Cowboy Bebop',
    genres: ['Action', 'Sci-Fi'],
    averageScore: 89,
    synopsis: 'Bounty hunters in space chasing criminals across the solar system.',
  };

  it('displays the welcome and how-it-works hero guide when message feed is empty', () => {
    /**
     * Verifies that the empty state guide renders on initial load
     * before any conversational turns have commenced.
     */
    render(<ChatPage />);

    expect(screen.getByText('Find Your Next Anime Obsession')).toBeInTheDocument();
    expect(screen.getByText('How it works')).toBeInTheDocument();
    expect(screen.getByText('Sub-1.5s Discovery')).toBeInTheDocument();
    expect(screen.getByText('Grounded Pitches')).toBeInTheDocument();
    expect(screen.getByText('Memory & Exclusion')).toBeInTheDocument();
  });

  it('appends user message and assistant placeholder upon submitting a prompt', async () => {
    /**
     * Verifies that submitting a prompt appends both the user bubble and active assistant bubble,
     * hiding the empty state guide and triggering streamChat.
     */
    let capturedParams: any = null;
    vi.mocked(chatStreamModule.streamChat).mockImplementation(async (params) => {
      capturedParams = params;
    });

    render(<ChatPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you feel like watching.../i);
    fireEvent.change(textarea, { target: { value: 'Atmospheric cyberpunk anime' } });

    const submitBtn = screen.getByRole('button', { name: /Send prompt/i });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    // Empty state guide should now be replaced by the conversation feed
    expect(screen.queryByText('How it works')).not.toBeInTheDocument();

    // User message bubble should be visible in the feed
    expect(screen.getByText('Atmospheric cyberpunk anime')).toBeInTheDocument();

    // Active assistant placeholder loading indicator should be visible
    expect(screen.getByText(/Finding anime that fit your mood/i)).toBeInTheDocument();

    // streamChat should have received the query and empty initial conversation history
    expect(capturedParams).not.toBeNull();
    expect(capturedParams.query).toBe('Atmospheric cyberpunk anime');
    expect(capturedParams.conversation_history).toEqual([]);
  });

  it('updates active assistant message with streaming tokens and candidate cards', async () => {
    /**
     * Verifies that onMetadata and onToken events update the corresponding assistant message.
     */
    vi.mocked(chatStreamModule.streamChat).mockImplementation(async (params) => {
      act(() => {
        params.onMetadata?.({
          query: params.query,
          session_id: 'session-xyz',
          count: 1,
          candidates: [sampleCandidate],
        });
      });

      act(() => {
        params.onToken?.('Cowboy Bebop is an absolute masterpiece of space jazz and neo-noir style.');
      });

      act(() => {
        params.onDone?.({
          status: 'complete',
          session_id: 'session-xyz',
        });
      });
    });

    render(<ChatPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you feel like watching.../i);
    fireEvent.change(textarea, { target: { value: 'Space western' } });
    const submitBtn = screen.getByRole('button', { name: /Send prompt/i });

    await act(async () => {
      fireEvent.click(submitBtn);
    });

    // Pitch text should be rendered
    expect(
      screen.getByText(/Cowboy Bebop is an absolute masterpiece of space jazz/i)
    ).toBeInTheDocument();

    // Candidate card should be rendered
    expect(screen.getByText('Cowboy Bebop')).toBeInTheDocument();
    expect(screen.getByText(/Bounty hunters in space/i)).toBeInTheDocument();
  });

  it('passes accumulated conversation history on subsequent conversation turns', async () => {
    /**
     * Verifies that the second turn serialises previous turns into conversation_history.
     */
    const callParams: any[] = [];
    vi.mocked(chatStreamModule.streamChat).mockImplementation(async (params) => {
      callParams.push(params);
      act(() => {
        params.onToken?.('Here are some great options for you.');
        params.onDone?.({ status: 'complete', session_id: 'session-123' });
      });
    });

    render(<ChatPage />);

    // First turn
    const textarea = screen.getByPlaceholderText(/Describe what you feel like watching.../i);
    fireEvent.change(textarea, { target: { value: 'First query' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Send prompt/i }));
    });

    expect(callParams[0].conversation_history).toEqual([]);

    // Second turn
    fireEvent.change(textarea, { target: { value: 'Second query' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Send prompt/i }));
    });

    expect(callParams.length).toBe(2);
    expect(callParams[1].query).toBe('Second query');
    expect(callParams[1].conversation_history).toEqual([
      { role: 'user', content: 'First query' },
      { role: 'assistant', content: 'Here are some great options for you.' },
    ]);
  });

  it('submits a new turn when More like this is clicked on a candidate card', async () => {
    /**
     * Verifies that clicking More like this triggers a new conversational turn
     * with query "More like <Title>".
     */
    const callParams: any[] = [];
    vi.mocked(chatStreamModule.streamChat).mockImplementation(async (params) => {
      callParams.push(params);
      act(() => {
        params.onMetadata?.({
          query: params.query,
          session_id: 'sess-1',
          count: 1,
          candidates: [sampleCandidate],
        });
        params.onDone?.({ status: 'complete', session_id: 'sess-1' });
      });
    });

    render(<ChatPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you feel like watching.../i);
    fireEvent.change(textarea, { target: { value: 'Jazz anime' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Send prompt/i }));
    });

    expect(screen.getByText('Cowboy Bebop')).toBeInTheDocument();

    const moreLikeBtn = screen.getByRole('button', { name: /More like this/i });
    await act(async () => {
      fireEvent.click(moreLikeBtn);
    });

    expect(callParams.length).toBe(2);
    expect(callParams[1].query).toBe('More like Cowboy Bebop');
  });

  it('displays the 429 rate limit countdown banner when rate limited', async () => {
    /**
     * Verifies that HTTP 429 rate limit errors display the active countdown banner
     * and disable the prompt input bar.
     */
    vi.mocked(chatStreamModule.streamChat).mockImplementation(async (params) => {
      act(() => {
        params.onError?.({
          status: 429,
          code: 'rate_limit_exceeded',
          message: 'Request quota exceeded. Please wait 30 seconds.',
          retryAfter: 30,
        });
      });
    });

    render(<ChatPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you feel like watching.../i);
    fireEvent.change(textarea, { target: { value: 'High rate query' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Send prompt/i }));
    });

    expect(screen.getByText('Rate Limit Cooling Down')).toBeInTheDocument();
    expect(screen.getByText('30s remaining')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Search paused \(30s remaining\)...|Describe what you feel like watching.../i)
    ).toBeDisabled();
  });

  it('resets conversation state to idle and stops streaming when Stop button is clicked', async () => {
    /**
     * Verifies that clicking the stop button immediately terminates stream,
     * clears active streaming indicators, and resets conversation state to idle.
     */
    let abortSignal: AbortSignal | undefined;
    vi.mocked(chatStreamModule.streamChat).mockImplementation(async (params) => {
      abortSignal = params.signal;
      // Keep stream pending until aborted
      return new Promise<void>((resolve) => {
        params.signal?.addEventListener('abort', () => resolve());
      });
    });

    render(<ChatPage />);

    const textarea = screen.getByPlaceholderText(/Describe what you feel like watching.../i);
    fireEvent.change(textarea, { target: { value: 'Long running generation' } });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Send prompt/i }));
    });

    // Stop button should now be visible in streaming state
    const stopBtn = screen.getByRole('button', { name: /Stop/i });
    expect(stopBtn).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(stopBtn);
    });

    // Abort signal should have fired
    expect(abortSignal?.aborted).toBe(true);

    // Send prompt button should be restored, confirming idle state
    expect(screen.getByRole('button', { name: /Send prompt/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Stop/i })).not.toBeInTheDocument();
  });
});
