// frontend/src/components/chat/ConciergePitch.tsx
import React, { useMemo, useState } from 'react';
import { Sparkles, EyeOff, Eye, Bot } from 'lucide-react';
import type { AnimeCandidate } from '../../types/chat';

export interface ConciergePitchProps {
  /**
   * The streamed pitch text content.
   */
  text?: string;
  /**
   * Backward-compatible alias for text.
   */
  pitch?: string;
  /**
   * List of retrieved candidates for citation title resolution and linking.
   */
  candidates?: AnimeCandidate[];
  /**
   * Whether the AI concierge response is currently streaming.
   */
  isStreaming?: boolean;
  className?: string;
  /**
   * Callback fired when a candidate citation chip is clicked.
   */
  onSelectAnime?: (animeId: number) => void;
  /**
   * Callback fired when a candidate citation chip is hovered or unhovered.
   */
  onHoverAnime?: (animeId: number | null) => void;
  plain?: boolean;
}

/**
 * Helper to resolve anime title from candidate metadata.
 */
function getCandidateTitle(candidate?: AnimeCandidate, animeId?: number): string {
  if (!candidate) return `Anime #${animeId}`;
  return (
    candidate.title_userPreferred ||
    candidate.title?.userPreferred ||
    candidate.title_english ||
    candidate.title?.english ||
    candidate.title_romaji ||
    candidate.title?.romaji ||
    `Anime #${animeId}`
  );
}

/**
 * Interactive citation chip for [anime:<id>] and [[anime:<id>]] tags.
 */
export const CitationChip: React.FC<{
  animeId: number;
  candidate?: AnimeCandidate;
  onSelectAnime?: (animeId: number) => void;
  onHoverAnime?: (animeId: number | null) => void;
}> = ({ animeId, candidate, onSelectAnime, onHoverAnime }) => {
  const title = getCandidateTitle(candidate, animeId);

  return (
    <button
      type="button"
      onClick={() => onSelectAnime?.(animeId)}
      onMouseEnter={() => onHoverAnime?.(animeId)}
      onMouseLeave={() => onHoverAnime?.(null)}
      className="inline-flex items-center gap-1 mx-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-brand/10 text-brand border border-brand/30 hover:bg-brand/20 hover:border-brand/50 hover:brightness-105 dark:bg-brand/20 dark:text-brand-light dark:border-brand/40 dark:hover:bg-brand/30 transition-all cursor-pointer select-none align-baseline shadow-xs"
      title={`Jump to ${title}`}
    >
      <Sparkles className="w-3 h-3 shrink-0 text-brand dark:text-brand-light" />
      <span className="truncate max-w-[200px]">{title}</span>
    </button>
  );
};

/**
 * Interactive spoiler badge for click-to-reveal spoilers.
 * Handles both safety-scrubbed [spoiler redacted] and inline ||spoiler content||.
 */
export const InteractiveSpoiler: React.FC<{
  isScrubbed: boolean;
  hiddenContent?: string;
}> = ({ isScrubbed, hiddenContent }) => {
  const [isRevealed, setIsRevealed] = useState(false);

  const toggleReveal = () => setIsRevealed((prev) => !prev);

  if (!isRevealed) {
    return (
      <button
        type="button"
        onClick={toggleReveal}
        className="inline-flex items-center gap-1 mx-1 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-100 text-amber-800 border border-amber-300 hover:bg-amber-200/80 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800/80 dark:hover:bg-amber-900/60 cursor-pointer transition-all duration-300 select-none align-baseline filter backdrop-blur-xs shadow-xs"
        title="Click to reveal spoiler"
        aria-expanded={false}
      >
        <EyeOff className="w-3 h-3 stroke-[2.2]" />
        <span>[Spoiler Redacted - click to reveal]</span>
      </button>
    );
  }

  const revealedText = isScrubbed
    ? '[Spoiler revealed: plot twist redacted for safety]'
    : hiddenContent || '[Spoiler revealed]';

  return (
    <button
      type="button"
      onClick={toggleReveal}
      className="inline-flex items-center gap-1 mx-1 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-800 border border-slate-300 hover:bg-slate-200 dark:bg-dark-800 dark:text-slate-200 dark:border-dark-700 dark:hover:bg-dark-700 cursor-pointer transition-all duration-300 select-none align-baseline shadow-xs animate-in fade-in-50"
      title="Click to hide spoiler"
      aria-expanded={true}
    >
      <Eye className="w-3 h-3 stroke-[2.2] text-slate-500 dark:text-slate-400" />
      <span className="italic">{revealedText}</span>
    </button>
  );
};

/**
 * Parses markdown inline bold (**text**), structured citation tokens ([anime:<id>] or [[anime:<id>]]),
 * scrubbed spoilers ([spoiler redacted]), and piped spoilers (||content||).
 */
export function renderFormattedInlineText(
  text: string,
  keyPrefix: string,
  candidates?: AnimeCandidate[],
  onSelectAnime?: (animeId: number) => void,
  onHoverAnime?: (animeId: number | null) => void
): React.ReactNode[] {
  // Regex to split on citations, spoilers, and bold
  const tokenPattern = /(\[{1,2}:?anime:\s*\d+\s*#?\]{1,2}|\[spoiler redacted\]|\|\|[\s\S]+?\|\||\*\*[^*]+\*\*)/gi;
  const parts = text.split(tokenPattern);

  return parts.map((part, index) => {
    const key = `${keyPrefix}-part-${index}`;
    if (!part) return null;

    // 1. Citation tag: [anime:<id>] or [[anime:<id>]]
    const citationMatch = part.match(/^\[{1,2}:?anime:\s*(\d+)\s*#?\]{1,2}$/i);
    if (citationMatch) {
      const animeId = parseInt(citationMatch[1], 10);
      const candidate = candidates?.find((c) => c.id === animeId);
      return (
        <CitationChip
          key={key}
          animeId={animeId}
          candidate={candidate}
          onSelectAnime={onSelectAnime}
          onHoverAnime={onHoverAnime}
        />
      );
    }

    // 2. Scrubbed spoiler: [spoiler redacted] (case-insensitive)
    if (/^\[spoiler redacted\]$/i.test(part)) {
      return (
        <InteractiveSpoiler
          key={key}
          isScrubbed={true}
        />
      );
    }

    // 3. Pipe spoiler: ||spoiler content||
    const pipeMatch = part.match(/^\|\|([\s\S]+?)\|\|$/);
    if (pipeMatch) {
      const hiddenContent = pipeMatch[1];
      return (
        <InteractiveSpoiler
          key={key}
          isScrubbed={false}
          hiddenContent={hiddenContent}
        />
      );
    }

    // 4. Inline bold: **bold text**
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      const inner = part.slice(2, -2);
      return (
        <strong key={key} className="font-semibold text-slate-900 dark:text-white">
          {inner}
        </strong>
      );
    }

    return <span key={key}>{part}</span>;
  });
}

export const ConciergePitch: React.FC<ConciergePitchProps> = ({
  pitch,
  text,
  candidates = [],
  isStreaming = false,
  className = '',
  onSelectAnime,
  onHoverAnime,
  plain = false,
}) => {
  const content = text ?? pitch ?? '';

  // Split pitch into paragraphs and bullet lists
  const renderedContent = useMemo(() => {
    if (!content && !isStreaming) return null;

    const rawBlocks = content.split(/\n\s*\n/);

    return rawBlocks.map((block, blockIndex) => {
      const trimmed = block.trim();
      if (!trimmed) return null;

      // Handle bullet lists (*, -, •, or numbered 1.)
      const lines = trimmed.split(/\n/);
      const isListItem = (line: string) => /^\s*([*\-•]|\d+\.)\s+/.test(line);
      const isList = lines.every((line) => isListItem(line));

      if (isList) {
        return (
          <ul key={`block-${blockIndex}`} className="space-y-1 my-2 list-disc list-inside">
            {lines.map((item, lIdx) => {
              const itemText = item.replace(/^\s*([*\-•]|\d+\.)\s+/, '');
              return (
                <li key={`item-${lIdx}`} className="text-slate-700 dark:text-slate-200">
                  {renderFormattedInlineText(
                    itemText,
                    `list-${blockIndex}-${lIdx}`,
                    candidates,
                    onSelectAnime,
                    onHoverAnime
                  )}
                </li>
              );
            })}
          </ul>
        );
      }

      return (
        <p key={`block-${blockIndex}`} className="text-slate-700 dark:text-slate-200 leading-relaxed">
          {renderFormattedInlineText(
            trimmed,
            `p-${blockIndex}`,
            candidates,
            onSelectAnime,
            onHoverAnime
          )}
        </p>
      );
    });
  }, [content, isStreaming, candidates, onSelectAnime, onHoverAnime]);

  if (!content && !isStreaming) {
    return null;
  }

  if (plain) {
    return (
      <div className={`space-y-2 ${className}`}>
        {renderedContent}
        {isStreaming && (
          <span
            className="inline-block w-1.5 h-4 ml-1 align-baseline bg-brand animate-pulse rounded-xs"
            aria-label="cursor"
          />
        )}
      </div>
    );
  }

  return (
    <div
      className={`relative rounded-xl border p-4 sm:p-5 transition-all duration-300 shadow-xs ${
        isStreaming
          ? 'border-brand/40 bg-gradient-to-br from-indigo-50/70 via-white to-white dark:from-brand-dark/15 dark:via-dark-900 dark:to-dark-900 ring-1 ring-brand/30 shadow-indigo-500/5'
          : 'border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900'
      } ${className}`}
    >
      {/* Header with Concierge Badge */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-100 dark:border-dark-800">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-brand text-white flex items-center justify-center shadow-xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white flex items-center gap-1.5">
              <span>Taste Concierge Pitch</span>
              {isStreaming && (
                <span className="flex h-2 w-2 relative">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-brand" />
                </span>
              )}
            </h4>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Grounded, spoiler-free pitch tailored to your mood
            </p>
          </div>
        </div>

        {isStreaming && (
          <div className="flex items-center gap-1 text-[11px] font-medium text-brand dark:text-brand-light">
            <Bot className="w-3.5 h-3.5 animate-bounce" />
            <span className="hidden sm:inline">Streaming AI commentary...</span>
          </div>
        )}
      </div>

      {/* Pitch Content */}
      <div className="space-y-3 text-sm">
        {content ? (
          <div>
            {renderedContent}
            {isStreaming && (
              <span
                className="inline-block w-1.5 h-4 ml-1 align-baseline bg-brand animate-pulse rounded-xs"
                aria-label="cursor"
              />
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 italic py-1">
            <span className="inline-block w-2 h-2 rounded-full bg-brand animate-ping" />
            <span>AI Concierge is synthesizing your personalized pitch...</span>
          </div>
        )}
      </div>
    </div>
  );
};
