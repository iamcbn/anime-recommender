// frontend/src/components/chat/AnimeCard.tsx
import React, { useState } from 'react';
import { Check, Sparkles, Film, Tv, ChevronDown, ChevronUp, ImageOff, Ban } from 'lucide-react';
import type { AnimeCandidate } from '../../types/chat';
import { useUserPreferences } from '../../hooks/useUserPreferences';
import { Badge } from '../common/Badge';

export interface AnimeCardProps {
  anime: AnimeCandidate;
  onMoreLikeThis: (title: string) => void;
  isHighlighted?: boolean;
}

export const AnimeCard: React.FC<AnimeCardProps> = ({
  anime,
  onMoreLikeThis,
  isHighlighted = false,
}) => {
  const { isSeen, toggleSeen, isGenreDisliked, toggleDislikedGenre } = useUserPreferences();
  const [isExpanded, setIsExpanded] = useState(false);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);

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
  const format = (anime.format || 'TV').toUpperCase();
  const genres = anime.genres || [];

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
                <div className="shrink-0">
                  <Badge variant={getScoreVariant(score)} size="sm">
                    {score}%
                  </Badge>
                </div>
              )}
            </div>

            {/* Subtitle / Metadata details */}
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span className="hidden md:inline-flex px-1.5 py-0.5 rounded font-mono font-medium text-[11px] bg-slate-100 dark:bg-dark-800 text-slate-700 dark:text-slate-300">
                {format}
              </span>
              {anime.episodes !== null && anime.episodes !== undefined && (
                <span className="flex items-center gap-1">
                  <Tv className="w-3.5 h-3.5" />
                  <span>{anime.episodes} {anime.episodes === 1 ? 'ep' : 'eps'}</span>
                </span>
              )}
              {anime.seasonYear && (
                <span>
                  {anime.season ? `${anime.season.toLowerCase()} ` : ''}{anime.seasonYear}
                </span>
              )}
              {anime.studios && anime.studios.length > 0 && (
                <span className="truncate max-w-[150px]">
                  by {anime.studios[0]}
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
        </div>

        {/* Interactive Action Bar */}
        <div className="mt-4 pt-3 border-t border-slate-100 dark:border-dark-800 flex flex-wrap items-center justify-between gap-2.5">
          {/* Seen Toggle */}
          <button
            type="button"
            onClick={() => toggleSeen(anime.id)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all focus:outline-none focus:ring-2 focus:ring-offset-1 select-none ${
              seen
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs focus:ring-emerald-500'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 dark:bg-dark-800 dark:hover:bg-dark-700 dark:text-slate-200 dark:border-dark-700 focus:ring-slate-400'
            }`}
          >
            <Check className={`w-3.5 h-3.5 ${seen ? 'stroke-[2.5]' : 'text-slate-400'}`} />
            <span>{seen ? 'Seen it' : 'Mark as seen'}</span>
          </button>

          {/* More Like This Button */}
          <button
            type="button"
            onClick={() => onMoreLikeThis(title)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-brand hover:text-brand-hover bg-brand/10 hover:bg-brand/15 dark:bg-brand/20 dark:hover:bg-brand/30 transition-colors focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-1 select-none"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>More like this</span>
          </button>
        </div>
      </div>
    </div>
  );
};
