// frontend/src/components/chat/ChatInput.tsx
import React, { useRef, useEffect } from 'react';
import { ArrowUp, Square, Sparkles, Shield, ShieldAlert } from 'lucide-react';
import { useUserPreferences } from '../../hooks/useUserPreferences';

export interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (query?: string) => void;
  onStop?: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  placeholder?: string;
}

const PROMPT_SUGGESTIONS = [
  'Dark psychological thriller like Death Note',
  'Heartwarming slice-of-life in rural Japan',
  'Mind-bending sci-fi with mystery and time travel',
  'High-octane shonen with incredible animation',
];

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSubmit,
  onStop,
  isStreaming,
  disabled = false,
  placeholder = 'Describe a mood, trope, or theme (e.g. "cyberpunk mystery with philosophical depth")...',
}) => {
  const { preferences, setAllowAdult } = useUserPreferences();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height to accommodate multi-line typing up to 160px
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && !isStreaming && value.trim()) {
        onSubmit();
      }
    }
  };

  const handleSuggestionClick = (prompt: string) => {
    if (disabled || isStreaming) return;
    onChange(prompt);
    onSubmit(prompt);
  };

  return (
    <div className="w-full space-y-3">
      {/* Primary Input Container */}
      <div className="relative rounded-2xl border border-slate-300 dark:border-dark-700 bg-white dark:bg-dark-900 shadow-sm focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20 transition-all">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          rows={1}
          className="w-full resize-none bg-transparent px-4 py-3.5 pr-28 text-sm sm:text-base text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none min-h-[52px] max-h-[160px] leading-relaxed disabled:opacity-50 disabled:cursor-not-allowed"
        />

        {/* Action Controls Inside Input (Right-aligned) */}
        <div className="absolute right-2.5 bottom-2.5 flex items-center gap-1.5">
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-red-600 hover:bg-red-700 text-white shadow-xs transition-colors focus:outline-none focus:ring-2 focus:ring-red-500"
              title="Stop generating"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              <span className="hidden sm:inline">Stop</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onSubmit()}
              disabled={disabled || !value.trim()}
              className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-brand hover:bg-brand-hover text-white shadow-xs transition-all disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-1"
              title="Send prompt (Enter)"
              aria-label="Send prompt"
            >
              <ArrowUp className="w-4 h-4 stroke-[2.5]" />
            </button>
          )}
        </div>
      </div>

      {/* Auxiliary Bar: Adult 18+ Toggle and Suggestions */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 pt-1 text-xs">
        {/* Quick Prompt Suggestions */}
        <div className="flex flex-wrap items-center gap-1.5 flex-1">
          <span className="hidden md:inline-flex items-center gap-1 text-slate-400 dark:text-slate-500 select-none mr-0.5">
            <Sparkles className="w-3 h-3 text-brand" />
            <span>Try:</span>
          </span>
          {PROMPT_SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => handleSuggestionClick(suggestion)}
              disabled={disabled || isStreaming}
              className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-600 hover:text-slate-900 border border-slate-200 dark:bg-dark-800 dark:hover:bg-dark-700 dark:text-slate-300 dark:hover:text-white dark:border-dark-700 transition-colors disabled:opacity-50 select-none truncate max-w-[280px] sm:max-w-none text-left"
            >
              {suggestion}
            </button>
          ))}
        </div>

        {/* Adult Content 18+ Toggle */}
        <div className="shrink-0 self-end sm:self-auto">
          <button
            type="button"
            onClick={() => setAllowAdult(!preferences.allow_adult)}
            disabled={disabled}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all select-none ${
              preferences.allow_adult
                ? 'bg-rose-100 text-rose-800 border-rose-300 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800/80 font-semibold'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-600 dark:bg-dark-800 dark:hover:bg-dark-700 dark:text-slate-400 border-slate-200 dark:border-dark-700'
            }`}
            title="Toggle inclusion of 18+ adult titles in recommendations"
          >
            {preferences.allow_adult ? (
              <ShieldAlert className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400" />
            ) : (
              <Shield className="w-3.5 h-3.5 text-slate-400" />
            )}
            <span>18+ Adult: {preferences.allow_adult ? 'On' : 'Off'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
