// frontend/src/components/layout/Footer.tsx
import React from 'react';
import { Terminal, ShieldCheck } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="w-full border-t border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-950 py-8 text-xs text-slate-500 dark:text-slate-500 mt-auto transition-colors duration-150">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-brand" />
          <span>Anime Recommender Semantic & Hybrid Retrieval Gateway</span>
        </div>

        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1 text-slate-600 dark:text-slate-400">
            <ShieldCheck className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
            Supabase Auth & RLS Protected
          </span>
          <span>•</span>
          <span>Sprint 6 Release</span>
        </div>
      </div>
    </footer>
  );
};
