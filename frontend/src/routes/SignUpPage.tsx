// frontend/src/routes/SignUpPage.tsx
import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Mail, Lock, Github, ArrowRight, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { Button } from '../components/common/Button';

export const SignUpPage: React.FC = () => {
  const { session, signUpWithPassword, signInWithGitHub } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const destination = (location.state as { from?: { pathname?: string } })?.from?.pathname || '/developers';

  useEffect(() => {
    if (session) {
      navigate(destination, { replace: true });
    }
  }, [session, navigate, destination]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);
    setIsSubmitting(true);

    try {
      const { error } = await signUpWithPassword(email.trim(), password);
      if (error) throw error;
      setSuccessMsg('Account created. Check your email to confirm your address, or sign in.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Sign up failed';
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
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white tracking-tight">
          Create your developer account
        </h1>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Generate API keys and integrate anime recommendations into your applications.
        </p>
      </div>

      <div className="bg-white dark:bg-dark-900 border border-slate-200 dark:border-dark-800 rounded-lg p-6 shadow-sm transition-colors">
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
          <span className="bg-white dark:bg-dark-900 px-3 text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium absolute">
            or register with email
          </span>
        </div>

        {successMsg ? (
          <div className="p-4 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 rounded-lg text-center flex flex-col items-center gap-2.5">
            <CheckCircle2 className="w-6 h-6 text-emerald-500 dark:text-emerald-400" />
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Check your email</h3>
            <p className="text-xs text-slate-600 dark:text-slate-300">
              {successMsg}
            </p>
            <Link
              to="/login"
              className="mt-2 text-xs font-medium text-slate-900 dark:text-white underline"
            >
              Go to log in &rarr;
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  className="w-full pl-9 pr-3.5 py-2 rounded-md bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand text-sm"
                />
              </div>
            </div>

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
                  className="w-full pl-9 pr-3.5 py-2 rounded-md bg-slate-50 dark:bg-dark-950 border border-slate-300 dark:border-dark-700 text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand text-sm"
                />
              </div>
            </div>

            {/* Legal consent statement */}
            <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-normal">
              By creating an account, you agree to our{' '}
              <Link to="/terms" className="underline hover:text-slate-900 dark:hover:text-white transition-colors">
                Terms of Service
              </Link>{' '}
              and{' '}
              <Link to="/privacy" className="underline hover:text-slate-900 dark:hover:text-white transition-colors">
                Privacy Policy
              </Link>.
            </p>

            {errorMsg && (
              <div className="p-3 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-md text-xs text-red-700 dark:text-red-300 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-500 dark:text-red-400 shrink-0 mt-0.5" />
                <span>{errorMsg}</span>
              </div>
            )}

            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting}
              className="w-full mt-1 py-2 justify-center"
              icon={<ArrowRight className="w-4 h-4" />}
            >
              Create account
            </Button>
          </form>
        )}
      </div>

      <div className="mt-5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-slate-900 dark:text-white underline">
            Log in
          </Link>
        </span>
        <Link to="/docs" className="hover:text-slate-800 dark:hover:text-white transition-colors">
          Documentation &rarr;
        </Link>
      </div>
    </div>
  );
};
