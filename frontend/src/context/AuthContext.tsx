// frontend/src/context/AuthContext.tsx
import React, { createContext, useEffect, useState, useMemo, useCallback } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from '../lib/supabase';
import type { AuthenticatedUser, AuthState } from '../types/auth';

interface AuthContextValue extends AuthState {
  signInWithMagicLink: (email: string) => Promise<{ error: Error | null }>;
  signInWithPassword: (email: string, password: string) => Promise<{ error: Error | null }>;
  signUpWithPassword: (email: string, password: string) => Promise<{ error: Error | null }>;
  signInWithGitHub: () => Promise<{ error: Error | null }>;
  signOut: () => Promise<void>;
  refreshUserRole: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<Session | null>(null);
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Derive admin role strictly from app_metadata (never user_metadata)
  const isAdmin = useMemo(() => {
    return Boolean(user?.app_metadata?.role === 'admin');
  }, [user]);

  useEffect(() => {
    // 1. Initial session load
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser((session?.user as AuthenticatedUser) ?? null);
      setIsLoading(false);
    });

    // 2. Subscribe to auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, currentSession) => {
      setSession(currentSession);
      setUser((currentSession?.user as AuthenticatedUser) ?? null);
      setIsLoading(false);
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  const signInWithMagicLink = useCallback(async (email: string) => {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/developers`,
      },
    });
    return { error: error as Error | null };
  }, []);

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    return { error: error as Error | null };
  }, []);

  const signUpWithPassword = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/developers`,
      },
    });
    return { error: error as Error | null };
  }, []);

  const signInWithGitHub = useCallback(async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'github',
      options: {
        redirectTo: `${window.location.origin}/developers`,
      },
    });
    return { error: error as Error | null };
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
    setUser(null);
  }, []);

  // Allows instant promotion reflection when an operator sets app_metadata in SQL
  const refreshUserRole = useCallback(async () => {
    const { data, error } = await supabase.auth.refreshSession();
    if (!error && data.session) {
      setSession(data.session);
      setUser((data.session.user as AuthenticatedUser) ?? null);
    }
  }, []);

  const value = useMemo(
    () => ({
      user,
      session,
      isLoading,
      isAdmin,
      signInWithMagicLink,
      signInWithPassword,
      signUpWithPassword,
      signInWithGitHub,
      signOut,
      refreshUserRole,
    }),
    [user, session, isLoading, isAdmin, signInWithMagicLink, signInWithPassword, signUpWithPassword, signInWithGitHub, signOut, refreshUserRole]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
