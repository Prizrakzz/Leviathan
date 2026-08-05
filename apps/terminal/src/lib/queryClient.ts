import { QueryCache, QueryClient } from '@tanstack/react-query';

/**
 * The app's ONE QueryClient factory (D-TW-6).
 *
 * Every read in the terminal is a react-query query, and react-query turns a failure into `isError`
 * state and nothing else. That is why the 2026-07-12 misdeploy produced ELEVEN failed API calls and ZERO
 * console messages: threads, profile and notifications all failed silently, the sidebar's red line was
 * the only visible trace, and a user's bug report would have been undebuggable.
 *
 * The cache-level `onError` is the single seam that breadcrumbs ALL of them at once — including queries
 * added later, which is the point: no future call site can forget it. It LOGS ONLY. Every visible error
 * state stays exactly where it is (D-TW-6 is explicitly not a UI change).
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
    queryCache: new QueryCache({
      // The key identifies WHICH read died (['threads'], ['profile'], ['thread-turns', id], ...); the
      // error carries the server's own `detail` sentence now that api/errors.ts lifts it.
      onError: (err, query) => {
        console.error(`[query] ${JSON.stringify(query.queryKey)} failed:`, err);
      },
    }),
  });
}
