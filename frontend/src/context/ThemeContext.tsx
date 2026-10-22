// frontend/src/context/ThemeContext.tsx
import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react';

export type Theme = 'light' | 'dark' | 'system';

export interface ThemeContextValue {
  theme: Theme;
  isDark: boolean;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const STORAGE_KEY = 'theme';
const SYSTEM_TRACK_KEY = 'theme_system';

export const ThemeContext = createContext<ThemeContextValue | null>(null);

function getSystemPrefersDark(): boolean {
  if (typeof window === 'undefined') return false;
  return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // 1. Initial theme choice: explicit stored preference, or fallback to 'system'
  const [theme, setThemeState] = useState<Theme>(() => {
    if (typeof window === 'undefined') return 'system';
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
      const storedSystem = localStorage.getItem(SYSTEM_TRACK_KEY);
      const systemDark = getSystemPrefersDark();
      const currentSystem = systemDark ? 'dark' : 'light';

      // If system preference changed since manual override was set, device setting takes priority
      if (stored && storedSystem && storedSystem !== currentSystem) {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(SYSTEM_TRACK_KEY);
        return 'system';
      }

      if (stored === 'light' || stored === 'dark') {
        return stored;
      }
    } catch {}
    return 'system';
  });

  // Track system preference state
  const [systemDark, setSystemDark] = useState<boolean>(getSystemPrefersDark);

  // Listen to OS-level preference changes dynamically
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const syncTheme = () => {
      const currentPrefersDark = mediaQuery.matches;
      setSystemDark(currentPrefersDark);
      // When the user's device theme setting changes, automatically adopt device setting
      setThemeState('system');
      try {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(SYSTEM_TRACK_KEY);
      } catch {}
    };

    const handleMediaChange = () => {
      syncTheme();
    };

    // Support both modern addEventListener and legacy addListener
    try {
      if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', handleMediaChange);
      } else if (mediaQuery.addListener) {
        mediaQuery.addListener(handleMediaChange);
      }
    } catch {}

    // Check on window focus and document visibilitychange in case user switched OS mode while in another app
    const handleFocusOrVisible = () => {
      if (mediaQuery.matches !== systemDark) {
        syncTheme();
      }
    };

    window.addEventListener('focus', handleFocusOrVisible);
    document.addEventListener('visibilitychange', handleFocusOrVisible);

    return () => {
      try {
        if (mediaQuery.removeEventListener) {
          mediaQuery.removeEventListener('change', handleMediaChange);
        } else if (mediaQuery.removeListener) {
          mediaQuery.removeListener(handleMediaChange);
        }
      } catch {}
      window.removeEventListener('focus', handleFocusOrVisible);
      document.removeEventListener('visibilitychange', handleFocusOrVisible);
    };
  }, [systemDark]);

  // Compute effective dark state: explicit 'dark', or 'system' matching system preference
  const isDark = useMemo(() => {
    if (theme === 'dark') return true;
    if (theme === 'light') return false;
    return systemDark;
  }, [theme, systemDark]);

  // Apply or remove .dark class on <html>
  useEffect(() => {
    const root = document.documentElement;
    if (isDark) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  }, [isDark]);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    try {
      if (newTheme === 'system') {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(SYSTEM_TRACK_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, newTheme);
        localStorage.setItem(SYSTEM_TRACK_KEY, getSystemPrefersDark() ? 'dark' : 'light');
      }
    } catch {}
  }, []);

  const toggleTheme = useCallback(() => {
    const nextIsDark = !isDark;
    const currentSystemDark = getSystemPrefersDark();

    // If toggling back to matching the device theme, clear override
    if (nextIsDark === currentSystemDark) {
      setThemeState('system');
      try {
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(SYSTEM_TRACK_KEY);
      } catch {}
    } else {
      const nextTheme: Theme = nextIsDark ? 'dark' : 'light';
      setThemeState(nextTheme);
      try {
        localStorage.setItem(STORAGE_KEY, nextTheme);
        localStorage.setItem(SYSTEM_TRACK_KEY, currentSystemDark ? 'dark' : 'light');
      } catch {}
    }
  }, [isDark]);

  const value = useMemo(
    () => ({
      theme,
      isDark,
      toggleTheme,
      setTheme,
    }),
    [theme, isDark, toggleTheme, setTheme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const useTheme = (): ThemeContextValue => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};
