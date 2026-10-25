// frontend/src/components/chat/AnimeCard.tsx
import React, { useState } from 'react';
import { Check, Sparkles, Film, Tv, ChevronDown, ChevronUp, ImageOff, Ban, Loader2, ThumbsUp, ThumbsDown } from 'lucide-react';
import { sendFeedback } from '../../lib/apiClient';
import { trackRecommendationClicked } from '../../lib/analytics';
import type { AnimeCandidate } from '../../types/chat';
import { useUserPreferences } from '../../hooks/useUserPreferences';
import { streamSinglePitch } from '../../lib/chatStream';
import { Badge } from '../common/Badge';
import { ConciergePitch } from './ConciergePitch';

export interface AnimeCardProps {
  anime: AnimeCandidate;
  onMoreLikeThis: (title: string) => void;
  isHighlighted?: boolean;
  query?: string;
  recommendationId?: string;
  position?: number;
}

/**
 * Safely extracts a displayable studio name string from heterogeneous studio data.
 * AniList schemas may return raw strings or nested objects containing node.name or name.
 */
export const getStudioName = (studio: unknown): string | null => {
  if (!studio) return null;
  if (typeof studio === 'string') {
    const trimmed = studio.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof studio === 'object') {
    const obj = studio as Record<string, unknown>;
    const node = obj.node as Record<string, unknown> | undefined;
    if (node && typeof node.name === 'string' && node.name.trim().length > 0) {
      return node.name.trim();
    }
    if (typeof obj.name === 'string' && obj.name.trim().length > 0) {
      return obj.name.trim();
    }
  }
  return null;
};

export const AnimeCard: React.FC<AnimeCardProps> = ({
  anime,
  onMoreLikeThis,
  isHighlighted = false,
  query = '',
  recommendationId,
  position,
}) => {
  const { isSeen, toggleSeen, isGenreDisliked, toggleDislikedGenre } = useUserPreferences();
  const [isExpanded, setIsExpanded] = useState(false);
  const [showCuratorNote, setShowCuratorNote] = useState(false);
  const [curatorPitch, setCuratorPitch] = useState<string>(anime.curator_note || (anime as any).curatorNote || '');
  const [isStreamingPitch, setIsStreamingPitch] = useState(false);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<'thumbs_up' | 'thumbs_down' | null>(null);

  const handleFeedback = (type: 'thumbs_up' | 'thumbs_down') => {
    setFeedbackStatus(type);
    if (recommendationId) {
      sendFeedback({
        recommendation_id: recommendationId,
        event_type: type,
        anime_id: anime.id,
        metadata: { title },
      });
    }
  };

  const handleToggleSeen = () => {
    toggleSeen(anime.id);
    if (!seen && recommendationId) {
      sendFeedback({
        recommendation_id: recommendationId,
        event_type: 'watchlist_add',
        anime_id: anime.id,
        metadata: { title },
      });
    }
  };

  const handleMoreLikeThisClick = () => {
    if (recommendationId) {
      sendFeedback({
        recommendation_id: recommendationId,
        event_type: 'more_like_this',
        anime_id: anime.id,
        metadata: { title },
      });
    }
    trackRecommendationClicked({
      anime_id: anime.id,
      position,
      format: anime.format || undefined,
    });
    onMoreLikeThis(title);
  };

  const title =
    anime.title_userPreferred ||
    anime.title?.userPreferred ||
    anime.title_english ||
    anime.title?.english ||
    anime.title_romaji ||
    anime.title?.romaji ||
    'Untitled Anime';

  const coverUrl =
    anime.coverImage_large ||
    anime.coverImage?.large ||
    anime.coverImage_medium ||
    anime.coverImage?.medium;

  const rawSynopsis = anime.synopsis || anime.description || 'No synopsis available.';
  // Strip HTML tags commonly returned by Anilist API
  const cleanSynopsis = rawSynopsis.replace(/<[^>]*>?/gm, '').trim();
  const isSynopsisLong = cleanSynopsis.length > 170;
  const displayedSynopsis =
    isExpanded || !isSynopsisLong
      ? cleanSynopsis
      : `${cleanSynopsis.slice(0, 170).trim()}...`;

  const seen = isSeen(anime.id);
  const score = anime.averageScore ?? anime.meanScore;
  const displayYear = anime.seasonYear ? Math.round(Number(anime.seasonYear)) : null;
  const displayEpisodes =
    anime.episodes !== null && anime.episodes !== undefined ? Math.round(Number(anime.episodes)) : null;
  const format = (anime.format || 'TV').toUpperCase();
  const isMovie = format === 'MOVIE';
  const FormatIcon = isMovie ? Film : Tv;

  const genres = anime.genres || [];
  const studioName =
    anime.studios && anime.studios.length > 0
      ? anime.studios.map(getStudioName).find((name): name is string => Boolean(name)) || null
      : null;

  const curatorNote = anime.curator_note || (anime as any).curatorNote;
  const exclusionBadge = anime.exclusion_badge || (anime as any).exclusionBadge;

  const curatorRationale = React.useMemo(() => {
    if (curatorNote) return curatorNote;
    const topGenres = genres.length > 0 ? genres.slice(0, 3).join(', ') : '';
    const roundedScore = score !== null && score !== undefined ? Math.round(Number(score)) : null;

    if (topGenres && roundedScore !== null) {
      return `Curator Note: Ranked among top matches. Features ${topGenres} with an acclaimed ${roundedScore}% AniList community rating.`;
    }
    if (topGenres) {
      return `Curator Note: Ranked among top matches. Features ${topGenres}.`;
    }
    if (roundedScore !== null) {
      return `Curator Note: Ranked among top matches with an acclaimed ${roundedScore}% AniList community rating.`;
    }
    return 'Curator Note: Ranked among top matches based on synopsis and thematic relevance.';
  }, [curatorNote, genres, score]);

  const handleToggleCuratorNote = async () => {
    if (showCuratorNote) {
      setShowCuratorNote(false);
      return;
    }
    setShowCuratorNote(true);

    if (!curatorPitch && !isStreamingPitch) {
      setIsStreamingPitch(true);
      try {
        await streamSinglePitch({
          animeId: anime.id,
          query: query || '',
          onToken: (tok) => {
            setCuratorPitch((prev) => prev + tok);
          },
          onDone: (finalPitch) => {
            setIsStreamingPitch(false);
            if (!finalPitch) {
              setCuratorPitch((prev) => prev || curatorRationale);
            }
          },
          onError: () => {
            setIsStreamingPitch(false);
            setCuratorPitch((prev) => prev || curatorRationale);
          },
        });
      } catch {
        setIsStreamingPitch(false);
        setCuratorPitch((prev) => prev || curatorRationale);
      }
    }
  };

  const getScoreVariant = (val: number): 'success' | 'brand' | 'warning' | 'neutral' => {
    if (val >= 80) return 'success';
    if (val >= 68) return 'brand';
    if (val >= 50) return 'warning';
    return 'neutral';
  };

  return (
    <div
      id={`anime-card-${anime.id}`}
      className={`group relative flex flex-col md:flex-row rounded-xl border transition-all duration-300 overflow-hidden shadow-xs hover:shadow-md ${
        isHighlighted
          ? 'ring-2 ring-brand-500 shadow-xl shadow-brand-500/20 scale-[1.01] border-brand-500 dark:border-brand-400 bg-brand/5 dark:bg-brand/10'
          : seen
          ? 'border-emerald-500/70 ring-2 ring-emerald-500/40 bg-emerald-50/20 dark:bg-emerald-950/20 dark:border-emerald-500/50'
          : 'border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-900 hover:border-slate-300 dark:hover:border-dark-700'
      }`}
    >
      {/* Seen Badge Indicator */}
      {seen && (
        <div className="absolute top-2.5 right-2.5 z-10 flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-600 text-white shadow-xs">
          <Check className="w-3 h-3 stroke-[3]" />
          <span>Seen</span>
        </div>
      )}

      {/* Cover Image Container */}
      <div className="relative w-full md:w-44 lg:w-48 shrink-0 bg-slate-100 dark:bg-dark-950 self-stretch min-h-[220px] md:min-h-full overflow-hidden flex items-center justify-center">
        {coverUrl && !imgError ? (
          <>
            {!imgLoaded && (
              <div className="absolute inset-0 animate-pulse bg-slate-200 dark:bg-dark-800 flex items-center justify-center">
                <Film className="w-8 h-8 text-slate-400 dark:text-dark-600 animate-spin" />
              </div>
            )}
            <img
              src={coverUrl}
              alt={title}
              loading="lazy"
              referrerPolicy="no-referrer"
              onLoad={() => setImgLoaded(true)}
              onError={() => setImgError(true)}
              className={`w-full h-full object-cover transition-all duration-300 group-hover:scale-105 ${
                imgLoaded ? 'opacity-100' : 'opacity-0'
              }`}
            />
          </>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 p-6 text-slate-400 dark:text-dark-600 text-center">
            <ImageOff className="w-8 h-8 stroke-1" />
            <span className="text-xs">No Cover</span>
          </div>
        )}

        {/* Format Pill Overlay on Mobile */}
        <div className="md:hidden absolute bottom-2 left-2">
          <span className="px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase bg-slate-900/80 text-white backdrop-blur-xs">
            {format}
          </span>
        </div>
      </div>

      {/* Card Content Body */}
      <div className="flex flex-col flex-1 p-4 sm:p-5 justify-between">
        <div className="space-y-3">
          {/* Header Row: Title and Badges */}
          <div>
            <div className="flex items-start justify-between gap-3">
              <h3
                className="text-base sm:text-lg font-bold text-slate-900 dark:text-white tracking-tight leading-snug line-clamp-2"
                title={title}
              >
                {title}
              </h3>

              {/* Score Badge */}
              {score !== null && score !== undefined && (
                <div className="shrink-0" title={`AniList Community Rating: ${(Number(score) / 10).toFixed(1)} / 10`}>
                  <Badge variant={getScoreVariant(Number(score))} size="sm">
                    ★ {(Number(score) / 10).toFixed(1)}
                  </Badge>
                </div>
              )}
            </div>

            {/* Subtitle / Metadata details */}
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span className="hidden md:inline-flex px-1.5 py-0.5 rounded font-mono font-medium text-[11px] bg-slate-100 dark:bg-dark-800 text-slate-700 dark:text-slate-300">
                {format}
              </span>
              {displayEpisodes !== null && (
                <span className="flex items-center gap-1">
                  <FormatIcon className="w-3.5 h-3.5" />
                  <span>
                    {isMovie
                      ? displayEpisodes > 1
                        ? `${displayEpisodes} parts`
                        : 'Movie'
                      : `${displayEpisodes} ${displayEpisodes === 1 ? 'ep' : 'eps'}`}
                  </span>
                </span>
              )}
              {displayYear !== null && (
                <span>
                  {anime.season ? `${anime.season.toLowerCase()} ` : ''}{displayYear}
                </span>
              )}
              {studioName && (
                <span className="truncate max-w-[150px]">
                  by {studioName}
                </span>
              )}
            </div>
          </div>

          {/* Clickable Genre Tags */}
          {genres.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {genres.map((genre) => {
                const disliked = isGenreDisliked(genre);
                return (
                  <button
                    key={genre}
                    type="button"
                    onClick={() => toggleDislikedGenre(genre)}
                    title={
                      disliked
                        ? `"${genre}" is in your disliked list (click to re-enable)`
                        : `Click to dislike "${genre}" and exclude it from future searches`
                    }
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium transition-all ${
                      disliked
                        ? 'line-through bg-red-100 text-red-800 border border-red-300 dark:bg-red-950/60 dark:text-red-300 dark:border-red-800/80 opacity-80'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 dark:bg-dark-800 dark:hover:bg-dark-700 dark:text-slate-300 dark:border-dark-700'
                    }`}
                  >
                    {disliked && <Ban className="w-2.5 h-2.5 text-red-500" />}
                    <span>{genre}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Soft Exclusion Badge Tag (Positioned cleanly under genres) */}
          {exclusionBadge && (
            <div className="pt-0.5">
              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-800 bg-amber-100/80 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-300 dark:border-amber-800/80 px-2 py-0.5 rounded-md">
                {exclusionBadge}
              </span>
            </div>
          )}

          {/* Synopsis */}
          <div className="text-xs sm:text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
            <p className="inline">{displayedSynopsis}</p>
            {isSynopsisLong && (
              <button
                type="button"
                onClick={() => setIsExpanded(!isExpanded)}
                className="inline-flex items-center gap-0.5 ml-1.5 text-brand hover:text-brand-hover dark:text-brand-light font-medium select-none"
              >
                <span>{isExpanded ? 'Less' : 'Read more'}</span>
                {isExpanded ? (
                  <ChevronUp className="w-3.5 h-3.5" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5" />
                )}
              </button>
            )}
          </div>

          {/* Taste Concierge Pitch / Curator Note Panel */}
          {showCuratorNote && (
            <div className="mt-2.5 p-3.5 rounded-xl bg-amber-50/80 dark:bg-amber-950/40 border border-amber-200/90 dark:border-amber-800/60 text-xs sm:text-sm text-amber-950 dark:text-amber-100 leading-relaxed animate-in fade-in-50 duration-200 shadow-xs">
              <div className="flex items-center gap-1.5 font-semibold text-amber-800 dark:text-amber-300 mb-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
                <span>Taste Concierge Pitch</span>
                {isStreamingPitch && (
                  <span className="inline-flex items-center gap-1 ml-auto text-[11px] font-normal text-amber-600 dark:text-amber-400">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    <span>Curating...</span>
                  </span>
                )}
              </div>
              {curatorPitch ? (
                <ConciergePitch plain text={curatorPitch} candidates={[anime]} />
              ) : isStreamingPitch ? (
                <div className="space-y-2 py-1">
                  <div className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-300 font-medium">
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-600" />
                    <span>Curator synthesising tailored note...</span>
                  </div>
                  <div className="space-y-1.5 animate-pulse pt-1">
                    <div className="h-2.5 bg-amber-200/60 dark:bg-amber-800/40 rounded-full w-5/6" />
                    <div className="h-2.5 bg-amber-200/50 dark:bg-amber-800/30 rounded-full w-full" />
                    <div className="h-2.5 bg-amber-200/40 dark:bg-amber-800/20 rounded-full w-3/4" />
                  </div>
                </div>
              ) : (
                <ConciergePitch plain text={curatorRationale} candidates={[anime]} />
              )}
            </div>
          )}
        </div>

        {/* Interactive Action Bar */}
        <div className="mt-4 pt-3 border-t border-slate-100 dark:border-dark-800 flex flex-wrap items-center justify-between gap-2.5">
          {/* Seen Toggle */}
          <button
            type="button"
            onClick={handleToggleSeen}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all focus:outline-none focus:ring-2 focus:ring-offset-1 select-none ${
              seen
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs focus:ring-emerald-500'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 dark:bg-dark-800 dark:hover:bg-dark-700 dark:text-slate-200 dark:border-dark-700 focus:ring-slate-400'
            }`}
          >
            <Check className={`w-3.5 h-3.5 ${seen ? 'stroke-[2.5]' : 'text-slate-400'}`} />
            <span>{seen ? 'Seen it' : 'Mark as seen'}</span>
          </button>

          <div className="flex flex-wrap items-center gap-2">
            {/* Curator Note Toggle Button */}
            <button
              type="button"
              onClick={handleToggleCuratorNote}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-amber-700 hover:text-amber-800 bg-amber-50 hover:bg-amber-100/80 dark:bg-amber-950/40 dark:text-amber-300 dark:hover:bg-amber-900/50 border border-amber-200/80 dark:border-amber-800/60 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-1 select-none"
              aria-expanded={showCuratorNote}
            >
              <Sparkles className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
              <span>Curator Note {showCuratorNote ? '▴' : '▾'}</span>
            </button>

            {/* First-Party Feedback Buttons (Thumbs Up / Down) */}
            <div className="inline-flex items-center gap-1 border border-slate-200 dark:border-dark-700 rounded-lg p-0.5 bg-slate-50 dark:bg-dark-900/60">
              <button
                type="button"
                onClick={() => handleFeedback('thumbs_up')}
                className={`p-1 rounded-md transition-colors focus:outline-none ${
                  feedbackStatus === 'thumbs_up'
                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
                    : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
                }`}
                aria-label="Thumbs up recommendation"
                title="Thumbs up"
              >
                <ThumbsUp className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => handleFeedback('thumbs_down')}
                className={`p-1 rounded-md transition-colors focus:outline-none ${
                  feedbackStatus === 'thumbs_down'
                    ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300'
                    : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
                }`}
                aria-label="Thumbs down recommendation"
                title="Thumbs down"
              >
                <ThumbsDown className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* More Like This Button */}
            <button
              type="button"
              onClick={handleMoreLikeThisClick}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-brand hover:text-brand-hover bg-brand/10 hover:bg-brand/15 dark:bg-brand/20 dark:hover:bg-brand/30 transition-colors focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-1 select-none"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>More like this</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
