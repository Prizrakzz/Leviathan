import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

function Boom({ crash }: { crash: boolean }) {
  if (crash) throw new Error('boom');
  return <div>ok</div>;
}

// React logs the caught error; silence it so the suite output stays clean.
afterEach(() => vi.restoreAllMocks());
const quiet = () => vi.spyOn(console, 'error').mockImplementation(() => {});

describe('ErrorBoundary (S2.1)', () => {
  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary fallback={<div>fallback</div>}>
        <Boom crash={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('ok')).toBeTruthy();
  });

  it('renders the fallback instead of unmounting the app when a child throws', () => {
    quiet();
    render(
      <ErrorBoundary fallback={<div>fallback</div>}>
        <Boom crash={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('fallback')).toBeTruthy();
  });

  it('passes the error + a reset to a function fallback', () => {
    quiet();
    render(
      <ErrorBoundary fallback={(err, reset) => <button onClick={reset}>{err.message}</button>}>
        <Boom crash={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('boom')).toBeTruthy();
  });

  it('clears the error when resetKeys change (self-heals on the next turn)', () => {
    quiet();
    const { rerender } = render(
      <ErrorBoundary fallback={<div>fallback</div>} resetKeys={['q1']}>
        <Boom crash={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('fallback')).toBeTruthy();
    rerender(
      <ErrorBoundary fallback={<div>fallback</div>} resetKeys={['q2']}>
        <Boom crash={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('ok')).toBeTruthy();
  });

  it('does NOT reset while resetKeys are unchanged', () => {
    quiet();
    const { rerender } = render(
      <ErrorBoundary fallback={<div>fallback</div>} resetKeys={['q1']}>
        <Boom crash={true} />
      </ErrorBoundary>,
    );
    rerender(
      <ErrorBoundary fallback={<div>fallback</div>} resetKeys={['q1']}>
        <Boom crash={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('fallback')).toBeTruthy(); // still showing the fallback
  });
});
