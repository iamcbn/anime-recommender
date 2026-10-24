// frontend/src/components/common/ErrorBoundary.test.tsx
/**
 * Unit tests for ErrorBoundary component.
 *
 * Conforms to Sprint 3 Unit Testing standards:
 * - Isolated Vitest execution.
 * - Strict British English documentation without em-dashes.
 */

import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from './ErrorBoundary';

// Helper component that throws an error when requested
const ProblematicChild: React.FC<{ shouldThrow?: boolean }> = ({ shouldThrow = false }) => {
  if (shouldThrow) {
    throw new Error('Simulated component render failure');
  }
  return <div>Healthy Child Content</div>;
};

describe('ErrorBoundary component', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it('renders children normally when no exception is thrown', () => {
    render(
      <ErrorBoundary>
        <ProblematicChild shouldThrow={false} />
      </ErrorBoundary>
    );

    expect(screen.getByText('Healthy Child Content')).toBeInTheDocument();
  });

  it('catches render exceptions and renders default fallback banner', () => {
    render(
      <ErrorBoundary>
        <ProblematicChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Rendering error encountered')).toBeInTheDocument();
    expect(screen.getByText(/Simulated component render failure/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('invokes onError callback with the caught exception', () => {
    const mockOnError = vi.fn();

    render(
      <ErrorBoundary onError={mockOnError}>
        <ProblematicChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(mockOnError).toHaveBeenCalledTimes(1);
    expect(mockOnError).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Simulated component render failure' }),
      expect.any(Object)
    );
  });

  it('renders custom fallback element when supplied', () => {
    render(
      <ErrorBoundary fallback={<div>Custom Fallback UI</div>}>
        <ProblematicChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText('Custom Fallback UI')).toBeInTheDocument();
  });

  it('allows recovery when reset is triggered after the underlying issue is resolved', () => {
    const ResettableContainer: React.FC = () => {
      const [hasFault, setHasFault] = useState(true);

      return (
        <div>
          <button type="button" onClick={() => setHasFault(false)}>
            Resolve Fault
          </button>
          <ErrorBoundary>
            <ProblematicChild shouldThrow={hasFault} />
          </ErrorBoundary>
        </div>
      );
    };

    render(<ResettableContainer />);

    // Initially in error state
    expect(screen.getByText('Rendering error encountered')).toBeInTheDocument();

    // Resolve fault in child
    fireEvent.click(screen.getByRole('button', { name: /resolve fault/i }));

    // Click try again on error boundary
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    // Now healthy child should be rendered
    expect(screen.getByText('Healthy Child Content')).toBeInTheDocument();
  });
});
