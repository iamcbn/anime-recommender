// frontend/src/components/chat/PreferenceDrawer.tsx
import React, { useState } from 'react';
import { SlidersHorizontal, ChevronDown, ChevronUp, X, RotateCcw, CheckCircle2, Ban } from 'lucide-react';
import { useUserPreferences } from '../../hooks/useUserPreferences';

export const PreferenceDrawer: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const {
    preferences,
    seenCount,
    dislikedGenresCount,
    clearSeen,
    removeDislikedGenre,
    clearDislikedGenres,
    resetPreferences,
  } = useUserPreferences();

  const hasPreferences = seenCount > 0 || dislikedGenresCount > 0 || preferences.allow_adult;

  return (
    <div className="w-full rounded-xl border border-slate-200 dark:border-dark-800 bg-slate-50/70 dark:bg-dark-900/50 backdrop-blur-xs overflow-hidden transition-all duration-200">
      {/* Collapsed Bar Trigger Header */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-2.5 flex items-center justify-between text-xs sm:text-sm text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors select-none"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2 flex-wrap">
          <SlidersHorizontal className="w-4 h-4 text-brand" />
          <span className="font-semibold">Discovery Preferences</span>
          <div className="flex items-center gap-1.5 ml-1">
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
              {seenCount} Seen
            </span>
            {dislikedGenresCount > 0 && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300">
                {dislikedGenresCount} Disliked {dislikedGenresCount === 1 ? 'Genre' : 'Genres'}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <span className="hidden sm:inline">{isOpen ? 'Hide filters' : 'Manage exclusions'}</span>
          {isOpen ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
        </div>
      </button>

      {/* Expanded Content Drawer */}
      {isOpen && (
        <div className="p-4 sm:p-5 border-t border-slate-200 dark:border-dark-800 space-y-4 bg-white dark:bg-dark-900 animate-in fade-in-50 duration-150">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Seen / Watched Anime Section */}
            <div className="p-3.5 rounded-lg border border-slate-200 dark:border-dark-800 bg-slate-50/50 dark:bg-dark-950/50 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                  <h5 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white">
                    Seen Titles
                  </h5>
                </div>
                {seenCount > 0 && (
                  <button
                    type="button"
                    onClick={clearSeen}
                    className="text-xs font-medium text-red-600 hover:text-red-700 dark:text-red-400 transition-colors"
                  >
                    Clear Seen
                  </button>
                )}
              </div>
              <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                {seenCount > 0 ? (
                  <span>
                    <strong className="text-slate-900 dark:text-white font-semibold">{seenCount} anime</strong> marked
                    seen (excluded from future searches).
                  </span>
                ) : (
                  'No anime marked seen yet. Click "Seen it" on any recommendation card to exclude it from future turns.'
                )}
              </p>
            </div>

            {/* Disliked Genres Section */}
            <div className="p-3.5 rounded-lg border border-slate-200 dark:border-dark-800 bg-slate-50/50 dark:bg-dark-950/50 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Ban className="w-4 h-4 text-red-500" />
                  <h5 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white">
                    Disliked Genres
                  </h5>
                </div>
                {dislikedGenresCount > 0 && (
                  <button
                    type="button"
                    onClick={clearDislikedGenres}
                    className="text-xs font-medium text-red-600 hover:text-red-700 dark:text-red-400 transition-colors"
                  >
                    Clear All
                  </button>
                )}
              </div>

              {dislikedGenresCount > 0 ? (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {preferences.disliked_genres.map((genre) => (
                    <span
                      key={genre}
                      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-950/70 dark:text-red-300 border border-red-200 dark:border-red-800/60"
                    >
                      <span>{genre}</span>
                      <button
                        type="button"
                        onClick={() => removeDislikedGenre(genre)}
                        className="hover:text-red-950 dark:hover:text-white transition-colors focus:outline-none"
                        title={`Remove exclusion for ${genre}`}
                        aria-label={`Remove exclusion for ${genre}`}
                      >
                        <X className="w-3 h-3 stroke-[2.5]" />
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                  No genres disliked. Click any genre chip on a recommendation card to exclude it from search.
                </p>
              )}
            </div>
          </div>

          {/* Bottom Bar: Reset Preferences Button */}
          {hasPreferences && (
            <div className="pt-2 border-t border-slate-100 dark:border-dark-800 flex justify-end">
              <button
                type="button"
                onClick={resetPreferences}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-white dark:hover:bg-dark-800 transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Reset all preferences</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
