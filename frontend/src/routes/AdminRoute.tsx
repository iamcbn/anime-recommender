// frontend/src/routes/AdminRoute.tsx
import React from 'react';
import { Navigate, Outlet, Link } from 'react-router-dom';
import { ShieldAlert, ArrowLeft, RefreshCw } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { Spinner } from '../components/common/Spinner';
import { Button } from '../components/common/Button';

export const AdminRoute: React.FC = () => {
  const { session, isAdmin, isLoading, refreshUserRole } = useAuth();
  const [isRefreshing, setIsRefreshing] = React.useState(false);

  if (isLoading) {
    return (
      <div className="min-h-[50vh] flex flex-col items-center justify-center gap-3">
        <Spinner size="lg" />
        <span className="text-xs text-slate-500 dark:text-slate-400">Verifying administrative role claims...</span>
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/login" replace />;
  }

  if (!isAdmin) {
    const handleRefresh = async () => {
      setIsRefreshing(true);
      await refreshUserRole();
      setIsRefreshing(false);
    };

    return (
      <div className="max-w-md mx-auto py-16 px-6 text-center bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-2xl shadow-xl flex flex-col items-center gap-4">
        <div className="w-14 h-14 rounded-2xl bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400 flex items-center justify-center">
          <ShieldAlert className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-bold text-slate-900 dark:text-white">Administrator Access Required</h2>
        <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
          The Telemetry Explorer is protected by Row Level Security (RLS) and requires an authenticated
          session with the <code className="bg-slate-100 dark:bg-dark-950 px-1.5 py-0.5 rounded text-indigo-600 dark:text-indigo-400 font-mono">app_metadata.role = &apos;admin&apos;</code> claim.
        </p>

        <div className="p-3 bg-slate-50 dark:bg-dark-950 border border-slate-200 dark:border-dark-800 rounded-lg text-left text-xs text-slate-600 dark:text-slate-400 w-full">
          <span className="text-slate-700 dark:text-slate-300 font-medium block mb-1">To grant admin access in Supabase:</span>
          <pre className="font-mono text-[11px] text-indigo-700 dark:text-indigo-300 overflow-x-auto p-1.5 bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded">
{`UPDATE auth.users
SET raw_app_meta_data =
  raw_app_meta_data || '{"role":"admin"}'::jsonb
WHERE email = '${session.user?.email || 'your-email@example.com'}';`}
          </pre>
        </div>

        <div className="flex items-center gap-3 mt-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefresh}
            isLoading={isRefreshing}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Check Role Again
          </Button>

          <Link to="/developers">
            <Button variant="primary" size="sm" icon={<ArrowLeft className="w-3.5 h-3.5" />}>
              Back to Developer Portal
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return <Outlet />;
};
