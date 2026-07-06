import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Rendered when a descendant throws. A function receives the error + a reset() to retry in place. */
  fallback: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  /** When any key changes, the caught error is cleared and children re-mount (self-heal on a new turn). */
  resetKeys?: unknown[];
  onError?: (error: Error, info: ErrorInfo) => void;
}
interface State {
  error: Error | null;
}

/** A React error boundary (S2.1). A throw anywhere below — INCLUDING a failed `lazy()` chunk load surfaced
 *  through Suspense (a rejected import promise throws to the nearest boundary) — renders `fallback` instead
 *  of unmounting the whole app, which on the dark theme reads as a "black screen". `resetKeys` clears the
 *  error when they change (e.g. a new question/contract) so a transient failure self-heals next turn. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.props.onError?.(error, info);
    // Surface it for CloudWatch/RUM without crashing the app.
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.error && keysChanged(prev.resetKeys, this.props.resetKeys)) {
      this.reset();
    }
  }

  reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (error) {
      const { fallback } = this.props;
      return typeof fallback === 'function' ? fallback(error, this.reset) : fallback;
    }
    return this.props.children;
  }
}

/** True when the reset keys differ (length change counts as changed). */
function keysChanged(a: unknown[] | undefined, b: unknown[] | undefined): boolean {
  if (a === b) return false;
  if (!a || !b || a.length !== b.length) return true;
  return a.some((x, i) => !Object.is(x, b[i]));
}
