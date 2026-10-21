// frontend/src/components/layout/Footer.tsx
import React from 'react';
import { Link } from 'react-router-dom';

export const Footer: React.FC = () => {
  return (
    <footer className="w-full border-t border-slate-200 dark:border-dark-800 bg-white dark:bg-dark-950 py-6 text-xs text-slate-500 dark:text-slate-500 mt-auto transition-colors duration-150">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <span className="font-medium text-slate-700 dark:text-slate-300">Anime Recommender API</span>
          <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-dark-900 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-dark-800">
            v1
          </span>
        </div>

        <div className="flex items-center gap-5">
          <Link to="/docs" className="hover:text-slate-900 dark:hover:text-slate-300 transition-colors">
            Documentation
          </Link>
          <Link to="/developers" className="hover:text-slate-900 dark:hover:text-slate-300 transition-colors">
            API Keys
          </Link>
        </div>
      </div>
    </footer>
  );
};
