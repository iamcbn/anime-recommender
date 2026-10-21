// frontend/src/routes/NotFoundPage.tsx
import React from 'react';
import { Link } from 'react-router-dom';
import { HelpCircle, ArrowLeft } from 'lucide-react';
import { Button } from '../components/common/Button';

export const NotFoundPage: React.FC = () => {
  return (
    <div className="max-w-md mx-auto py-20 px-6 text-center flex flex-col items-center gap-4">
      <div className="w-16 h-16 rounded-2xl bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 flex items-center justify-center text-slate-500 dark:text-slate-400 shadow-sm">
        <HelpCircle className="w-8 h-8" />
      </div>
      <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">404 - Not Found</h1>
      <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
        The requested page could not be located. Check the URL or return to the documentation.
      </p>
      <Link to="/docs" className="mt-2">
        <Button variant="primary" size="sm" icon={<ArrowLeft className="w-4 h-4" />}>
          Back to Documentation
        </Button>
      </Link>
    </div>
  );
};
