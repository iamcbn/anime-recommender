// frontend/src/App.tsx
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider } from './context/AuthContext';
import { RootLayout } from './components/layout/RootLayout';
import { ProtectedRoute } from './routes/ProtectedRoute';
import { AdminRoute } from './routes/AdminRoute';
import { LoginPage } from './routes/LoginPage';
import { SignUpPage } from './routes/SignUpPage';
import { TermsPage } from './routes/TermsPage';
import { PrivacyPage } from './routes/PrivacyPage';
import { DevelopersPage } from './routes/DevelopersPage';
import { AdminTelemetryPage } from './routes/AdminTelemetryPage';
import { AdminLlmUsagePage } from './routes/AdminLlmUsagePage';
import { DocsPage } from './routes/DocsPage';
import { ChatPage } from './routes/ChatPage';
import { NotFoundPage } from './routes/NotFoundPage';

export const App: React.FC = () => {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<RootLayout />}>
              {/* Consumer AI Discovery Chat Page at root / */}
              <Route index element={<ChatPage />} />
              <Route path="chat" element={<ChatPage />} />

              {/* Public Routes */}
              <Route path="docs" element={<DocsPage />} />
              <Route path="login" element={<LoginPage />} />
              <Route path="signup" element={<SignUpPage />} />
              <Route path="terms" element={<TermsPage />} />
              <Route path="privacy" element={<PrivacyPage />} />

              {/* Protected Routes (Authenticated Developer) */}
              <Route element={<ProtectedRoute />}>
                <Route path="developers" element={<DevelopersPage />} />

                {/* Admin-Only Protected Route (app_metadata.role === 'admin') */}
                <Route element={<AdminRoute />}>
                  <Route path="admin/telemetry" element={<AdminTelemetryPage />} />
                  <Route path="admin/llm-usage" element={<AdminLlmUsagePage />} />
                </Route>
              </Route>

              {/* 404 Fallback */}
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
};

export default App;
