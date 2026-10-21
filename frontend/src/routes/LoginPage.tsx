// frontend/src/routes/LoginPage.tsx
import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Mail, Lock, Github, Sparkles, CheckCircle2, ArrowRight, AlertCircle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { Button } from '../components/common/Button';

export const LoginPage: React.FC = () => {
  const { session, signInWithMagicLink, signInWithPassword, signUpWithPassword, signInWithGitHub } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [mode, setMode] = useState<'magic_link' | 'password' | 'signup'>('magic_link');
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [magicLinkSent, setMagicLinkSent] = useState<boolean>(false);

  const destination = (location.state as { from?: { pathname?: string } })?.from?.pathname || '/developers';

  useEffect(() => {
    if (session) {
      navigate(destination, { replace: true });
    }
  }, [session, navigate, destination]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setIsSubmitting(true);

    try {
      if (mode === 'magic_link') {
        const { error } = await signInWithMagicLink(email.trim());
        if (error) throw error;
        setMagicLinkSent(true);
      } else if (mode === 'password') {
        const { error } = await signInWithPassword(email.trim(), password);
        if (error) throw error;
        navigate(destination, { replace: true });
      } else if (mode === 'signup') {
        const { error } = await signUpWithPassword(email.trim(), password);
        if (error) throw error;
        setErrorMsg('Sign up successful! Please check your email to confirm your account.');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed';
      setErrorMsg(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleGitHubLogin = async () => {
    setErrorMsg(null);
    setIsSubmitting(true);
    try {
      const { error } = await signInWithGitHub();
      if (error) throw error;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'GitHub login failed';
      setErrorMsg(msg);
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-md mx-auto py-12 px-4 sm:px-6">
      <div className="text-center mb-8">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-gradient-to-tr from-brand to-indigo-400 text-white shadow-lg shadow-brand/20 mb-4">
          <Sparkles className="w-6 h-6" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">Developer Login</h1>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Sign in or create an account with Supabase Auth to manage your API keys.
        </p>
      </div>

      <div className="bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-2xl p-6 shadow-xl transition-colors">
        {/* GitHub OAuth Button */}
        <Button
          variant="secondary"
          className="w-full justify-center bg-slate-100 hover:bg-slate-200 border-slate-300 text-slate-800 dark:bg-dark-950 dark:hover:bg-dark-800 dark:border-dark-700 dark:text-white font-medium mb-6 py-2.5"
          onClick={handleGitHubLogin}
          isLoading={isSubmitting}
          icon={<Github className="w-4 h-4" />}
        >
          Continue with GitHub
        </Button>

        <div className="relative flex items-center justify-center mb-6">
          <div className="border-t border-slate-200 dark:border-dark-800 w-full" />
          <span className="bg-white dark:bg-dark-900 px-3 text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-semibold absolute">
            or continue with email
          </span>
        </div>

        {/* Tab Selection */}
        <div className="flex rounded-lg bg-slate-100 dark:bg-dark-950 p-1 mb-6 border border-slate-200 dark:border-dark-800 text-xs font-medium">
          <button
            type="button"
            onClick={() => {
              setMode('magic_link');
              setErrorMsg(null);
              setMagicLinkSent(false);
            }}
            className={`flex-1 py-1.5 rounded-md transition-colors ${
              mode === 'magic_link'
                ? 'bg-white dark:bg-brand text-slate-900 dark:text-white shadow-sm'
                : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
            }`}
          >
            Magic Link
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('password');
              setErrorMsg(null);
              setMagicLinkSent(false);
            }}
            className={`flex-1 py-1.5 rounded-md transition-colors ${
              mode === 'password'
                ? 'bg-white dark:bg-brand text-slate-900 dark:text-white shadow-sm'
                : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('signup');
              setErrorMsg(null);
              setMagicLinkSent(false);
            }}
            className={`flex-1 py-1.5 rounded-md transition-colors ${
              mode === 'signup'
                ? 'bg-white dark:bg-brand text-slate-900 dark:text-white shadow-sm'
                : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
            }`}
          >
            Sign Up
          </button>
        </div>

        {magicLinkSent ? (
          <div className="p-4 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 rounded-xl text-center flex flex-col items-center gap-3">
            <CheckCircle2 className="w-8 h-8 text-emerald-500 dark:text-emerald-400" />
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Check Your Inbox</h3>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              We&apos;ve dispatched a secure passwordless login link to{' '}
              <strong className="text-slate-900 dark:text-white">{email}</strong>. Click the link in your email to sign in.
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMagicLinkSent(false)}
              className="text-xs text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white mt-1"
            >
              Use a different email
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="developer@example.com"
                  required
                  className="w-full pl-9 pr-3.5 py-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand text-sm"
                />
              </div>
            </div>

            {mode !== 'magic_link' && (
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    required
                    minLength={6}
                    className="w-full pl-9 pr-3.5 py-2.5 rounded-lg bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand text-sm"
                  />
                </div>
              </div>
            )}

            {errorMsg && (
              <div className="p-3 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-lg text-xs text-red-700 dark:text-red-300 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0 mt-0.5" />
                <span>{errorMsg}</span>
              </div>
            )}

            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting}
              className="w-full mt-2 py-2.5 justify-center"
              icon={<ArrowRight className="w-4 h-4" />}
            >
              {mode === 'magic_link'
                ? 'Send Magic Link'
                : mode === 'password'
                ? 'Sign In'
                : 'Create Account'}
            </Button>
          </form>
        )}
      </div>

      <div className="text-center mt-6">
        <Link to="/docs" className="text-xs text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white transition-colors">
          View API Documentation &rarr;
        </Link>
      </div>
    </div>
  );
};
