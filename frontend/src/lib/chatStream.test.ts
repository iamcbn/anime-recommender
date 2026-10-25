// frontend/src/lib/chatStream.test.ts
/**
 * Unit tests for Server-Sent Events (SSE) streaming, fragmented chunk handling, and HTTP 429 rate limiting.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Fast, isolated execution using Vitest without network access.
 * - Strict British English documentation without em-dashes.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { streamChat, streamSinglePitch } from './chatStream';

describe('streamChat SSE Parser and Event Dispatcher', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    let index = 0;
    return new ReadableStream<Uint8Array>({
      pull(controller) {
        if (index < chunks.length) {
          controller.enqueue(encoder.encode(chunks[index]));
          index++;
        } else {
          controller.close();
        }
      },
    });
  }

  it('parses fragmented SSE chunks and dispatches metadata, token, warning, and done events', async () => {
    /**
     * Verifies that streamChat buffers partial frames across network chunk boundaries
     * and correctly dispatches parsed events to their respective callbacks.
     */
    // Split events across chunk boundaries to simulate fragmented TCP/HTTP delivery
    const chunk1 = 'event: metadata\ndata: {"request_id":"req-101","query":"cyber';
    const chunk2 = 'punk"}\n\nevent: token\ndata: {"text":"Welcome ';
    const chunk3 = 'to Night City"}\n\nevent: warning\ndata: {"category":"budget","message":"Low remaining tokens"}\n\nevent: done\ndata: {"request_id":"req-101","total_ms":250}\n\n';

    const mockResponse = {
      ok: true,
      status: 200,
      body: createMockStream([chunk1, chunk2, chunk3]),
    };
    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const onMetadata = vi.fn();
    const onToken = vi.fn();
    const onWarning = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    await streamChat({
      query: 'cyberpunk anime',
      onMetadata,
      onToken,
      onWarning,
      onDone,
      onError,
    });

    expect(onError).not.toHaveBeenCalled();

    // Verify metadata dispatch
    expect(onMetadata).toHaveBeenCalledTimes(1);
    expect(onMetadata).toHaveBeenCalledWith({
      request_id: 'req-101',
      query: 'cyberpunk',
    });

    // Verify token dispatch
    expect(onToken).toHaveBeenCalledTimes(1);
    expect(onToken).toHaveBeenCalledWith('Welcome to Night City');

    // Verify warning dispatch
    expect(onWarning).toHaveBeenCalledTimes(1);
    expect(onWarning).toHaveBeenCalledWith({
      category: 'budget',
      message: 'Low remaining tokens',
    });

    // Verify done dispatch
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledWith({
      request_id: 'req-101',
      total_ms: 250,
    });
  });

  it('dispatches SSE stream error events when the server yields an error packet', async () => {
    /**
     * Verifies that stream error events from backend guardrails or orchestrators
     * trigger onError with parsed category and detail messages.
     */
    const errorSse = 'event: error\ndata: {"category":"prompt_injection","detail":"Safety policy violation"}\n\n';

    const mockResponse = {
      ok: true,
      status: 200,
      body: createMockStream([errorSse]),
    };
    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const onError = vi.fn();

    await streamChat({
      query: 'ignore instructions',
      onError,
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 400,
        code: 'prompt_injection',
        message: 'Safety policy violation',
        detail: 'Safety policy violation',
      })
    );
  });

  it('parses HTTP 429 status code and extracts the Retry-After header duration', async () => {
    /**
     * Verifies that HTTP 429 rate limit responses extract the Retry-After header
     * and report structured retry intervals to the caller.
     */
    const headers = new Headers();
    headers.set('Retry-After', '45');

    const mockResponse = {
      ok: false,
      status: 429,
      headers,
      json: async () => ({
        error: { message: 'Too many requests. Please wait 45 seconds.' },
      }),
    };
    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const onError = vi.fn();

    await streamChat({
      query: 'rapid query',
      onError,
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith({
      status: 429,
      code: 'rate_limit_exceeded',
      message: 'Too many requests. Please wait 45 seconds.',
      retryAfter: 45,
    });
  });

  it('defaults Retry-After to 60 seconds when the header is missing or non-numeric', async () => {
    /**
     * Verifies fallback handling for rate limit errors when the server does not specify a Retry-After header.
     */
    const mockResponse = {
      ok: false,
      status: 429,
      headers: new Headers(),
      json: async () => ({}),
    };
    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const onError = vi.fn();

    await streamChat({
      query: 'rapid query without header',
      onError,
    });

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 429,
        code: 'rate_limit_exceeded',
        retryAfter: 60,
      })
    );
  });

  it('binds streamed tokens strictly to the requested anime ID in streamSinglePitch', async () => {
    /**
     * Verifies that streamSinglePitch filters out token events targeted to other anime IDs
     * and accumulates matching tokens into the final pitch.
     */
    const tokenChunks = [
      'event: token\ndata: {"anime_id":16049,"text":"A compelling sci-fi "}\n\n',
      'event: token\ndata: {"anime_id":99999,"text":"Mismatched token from another card"}\n\n',
      'event: token\ndata: {"anime_id":16049,"text":"set in Academy City."}\n\n',
      'event: done\ndata: {"status":"completed"}\n\n',
    ];

    const mockResponse = {
      ok: true,
      status: 200,
      body: createMockStream(tokenChunks),
    };
    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const onToken = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    await streamSinglePitch({
      animeId: 16049,
      query: 'why watch this',
      onToken,
      onDone,
      onError,
    });

    expect(onError).not.toHaveBeenCalled();
    expect(onToken).toHaveBeenCalledTimes(2);
    expect(onToken).toHaveBeenNthCalledWith(1, 'A compelling sci-fi ');
    expect(onToken).toHaveBeenNthCalledWith(2, 'set in Academy City.');
    expect(onDone).toHaveBeenCalledWith('A compelling sci-fi set in Academy City.');
  });

  it('dispatches fallback onDone when stream completes without an explicit done packet', async () => {
    /**
     * Verifies that the try...finally block ensures onDone is dispatched with fallback
     * metadata so that UI state machines do not hang in a perpetual streaming state.
     */
    const tokenChunks = [
      'event: token\ndata: {"text":"Partial text before socket close"}\n\n',
    ];

    const mockResponse = {
      ok: true,
      status: 200,
      body: createMockStream(tokenChunks),
    };
    globalThis.fetch = vi.fn().mockResolvedValue(mockResponse);

    const onToken = vi.fn();
    const onDone = vi.fn();
    const onError = vi.fn();

    await streamChat({
      query: 'abruptly closing stream',
      onToken,
      onDone,
      onError,
    });

    expect(onError).not.toHaveBeenCalled();
    expect(onToken).toHaveBeenCalledWith('Partial text before socket close');
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'completed',
      })
    );
  });
});
