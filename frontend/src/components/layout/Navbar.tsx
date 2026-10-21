// frontend/src/components/layout/Navbar.tsx
import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { Key, Shield, BookOpen, LogOut, LogIn, Sparkles, Sun, Moon } from 'lucide-react';
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
    `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
      isActive
        ? 'bg-slate-100 dark:bg-dark-800 text-slate-900 dark:text-white font-semibold'
        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100/70 dark:hover:bg-dark-900'
    }`;

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-200 dark:border-dark-800 bg-white/80 dark:bg-dark-950/80 backdrop-blur-md transition-colors duration-150">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand / Logo */}
        <Link to="/" className="flex items-center gap-2 text-slate-900 dark:text-white font-bold tracking-tight text-lg">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-brand to-indigo-400 flex items-center justify-center text-white shadow-md shadow-brand/20">
            <Sparkles className="w-4 h-4" />
          </div>
          <span>Anime Recommender</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-dark-700">
            Developer Portal
          </span>
        </Link>

        {/* Center Nav Links */}
        <nav className="hidden md:flex items-center gap-1">
          <NavLink to="/docs" className={navLinkClass}>
            <BookOpen className="w-4 h-4" />
            <span>Docs</span>
          </NavLink>
          <NavLink to="/developers" className={navLinkClass}>
            <Key className="w-4 h-4" />
            <span>API Keys</span>
          </NavLink>
          {isAdmin && (
            <NavLink to="/admin/telemetry" className={navLinkClass}>
              <Shield className="w-4 h-4 text-brand-light" />
              <span>Admin Telemetry</span>
            </NavLink>
          )}
        </nav>

        {/* Right Section: Theme Toggle + Auth */}
        <div className="flex items-center gap-3">
          {/* Theme Toggle Button */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-dark-800 transition-colors border border-transparent hover:border-slate-200 dark:hover:border-dark-700"
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label="Toggle light/dark theme"
          >
            {isDark ? (
              <Sun className="w-4 h-4 text-amber-400 animate-spin-slow" />
            ) : (
              <Moon className="w-4 h-4 text-slate-600" />
            )}
          </button>

          {user ? (
            <div className="flex items-center gap-3">
              <div className="hidden sm:flex flex-col items-end text-xs">
                <span className="text-slate-800 dark:text-slate-200 font-medium truncate max-w-[180px]">
                  {user.email}
                </span>
                <div className="flex items-center gap-1 mt-0.5">
                  {isAdmin ? (
                    <Badge variant="brand" size="sm">Admin</Badge>
                  ) : (
                    <Badge variant="neutral" size="sm">Developer</Badge>
                  )}
                </div>
              </div>
              <button
                onClick={handleSignOut}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-dark-800 transition-colors"
                title="Sign out"
              >
                <LogOut className="w-4 h-4" />
                <span className="hidden sm:inline">Sign Out</span>
              </button>
            </div>
          ) : (
            <Link
              to="/login"
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-medium bg-brand hover:bg-brand-hover text-white shadow-sm transition-colors"
            >
              <LogIn className="w-4 h-4" />
              <span>Sign In</span>
            </Link>
          )}
        </div>
      </div>
    </header>
  );
};
