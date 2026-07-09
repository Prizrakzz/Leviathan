import { Suspense } from 'react';
import { ErrorBoundary } from '@/shell/ErrorBoundary';
import type { Tab } from '@/store/tabs';
import { TAB_COMPONENTS } from './registry';

// React.lazy caches a REJECTED import forever (the S2.1 lesson) — a genuinely missing chunk (e.g. the
// just-deployed window) needs the reload escape; resetKeys alone cannot recover it.
const tabErrorFallback = (
  <div className="p-4 font-mono text-12 text-text-faint">
    couldn’t render this tab ·{' '}
    <button onClick={() => window.location.reload()} className="text-cyan hover:text-amber">
      reload
    </button>
  </div>
);

/** The active tab's body (P1.5): registry-resolved lazy component in its own boundary, so a failed tab
 *  chunk or a stale locator degrades LOCALLY — never the shell (the S2.x lesson). Mount-active-only: the
 *  inactive tabs are unmounted (pan/zoom resets on switch — accepted v1; keep-alive is the fallback). */
export default function TabDocument({ tab }: { tab: Tab }) {
  const Body = TAB_COMPONENTS[tab.kind];
  return (
    <ErrorBoundary fallback={tabErrorFallback} resetKeys={[tab.id]}>
      <Suspense fallback={<div className="h-full animate-pulse bg-bg-1" />}>
        {/* params cast: the registry pairs each kind with its component, which narrows its own params */}
        <Body params={tab.params as never} />
      </Suspense>
    </ErrorBoundary>
  );
}
