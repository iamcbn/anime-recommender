// frontend/src/components/layout/Navbar.tsx
import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { LogOut, LogIn, Sun, Moon } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useTheme } from '../../hooks/useTheme';
import { Badge } from '../common/Badge';

export const Navbar: React.FC = () => {
  const { user, isAdmin, signOut } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded-md text-sm transition-colors ${
      isActive
        ? 'bg-slate-100 dark:bg-dark-800 text-slate-900 dark:text-white font-medium'
        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100/70 dark:hover:bg-dark-900'
    }`;

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-200 dark:border-dark-800 bg-white/90 dark:bg-dark-950/90 backdrop-blur-sm transition-colors duration-150">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        {/* Brand + Nav */}
        <div className="flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2.5 text-slate-900 dark:text-white font-semibold tracking-tight text-sm">
            <div className="w-6 h-6 rounded bg-slate-900 dark:bg-white text-white dark:text-slate-950 font-mono text-[11px] font-bold flex items-center justify-center">
              AR
            </div>
            <span>Anime Recommender</span>
            <span className="text-slate-300 dark:text-dark-700 font-normal">/</span>
            <span className="text-slate-500 dark:text-slate-400 font-normal">Developers</span>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            <NavLink to="/" end className={navLinkClass}>
              Discovery
            </NavLink>
            <NavLink to="/docs" className={navLinkClass}>
              Docs
            </NavLink>
            <NavLink to="/developers" className={navLinkClass}>
              API Keys
            </NavLink>
            {isAdmin && (
              <>
                <NavLink to="/admin/telemetry" className={navLinkClass}>
                  Admin Telemetry
                </NavLink>
                <NavLink to="/admin/llm-usage" className={navLinkClass}>
                  LLM Usage
                </NavLink>
              </>
            )}
          </nav>
        </div>

        {/* Right Section: Theme Toggle + Auth */}
        <div className="flex items-center gap-3">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-md text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-dark-800 transition-colors"
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label="Toggle light/dark theme"
          >
            {isDark ? (
              <Sun className="w-4 h-4 text-slate-300" />
            ) : (
              <Moon className="w-4 h-4 text-slate-600" />
            )}
          </button>

          {user ? (
            <div className="flex items-center gap-3">
              <div className="hidden sm:flex items-center gap-2 text-xs">
                <span className="text-slate-700 dark:text-slate-300 font-mono truncate max-w-[180px]">
                  {user.email}
                </span>
                {isAdmin && <Badge variant="brand" size="sm">Admin</Badge>}
              </div>
              <button
                onClick={handleSignOut}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-800 transition-colors"
                title="Sign out"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Sign out</span>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <Link
                to="/login"
                className="px-2.5 py-1.5 rounded-md text-xs font-medium text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-800 transition-colors"
              >
                Log in
              </Link>
              <Link
                to="/signup"
                className="px-3 py-1.5 rounded-full text-xs font-medium bg-slate-900 hover:bg-slate-800 text-white dark:bg-white dark:hover:bg-slate-200 dark:text-slate-950 transition-colors shadow-xs"
              >
                Sign up
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
