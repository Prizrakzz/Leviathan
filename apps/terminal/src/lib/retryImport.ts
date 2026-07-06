/** Retry a dynamic `import()` once (by default) before giving up (S2.1). A just-deployed `index.html` can
 *  briefly reference a chunk the CDN hasn't served yet (the SPA 404→index.html rewrite then hands the
 *  importer HTML-with-200 instead of JS → the module load rejects). One retry after a short delay heals that
 *  transient window; the FINAL rejection still propagates so the Suspense error boundary shows its fallback
 *  rather than the whole tree unmounting. */
export function retryImport<T>(factory: () => Promise<T>, attempts = 2, delayMs = 1200): Promise<T> {
  return factory().catch((err) => {
    if (attempts <= 1) throw err;
    return new Promise<void>((resolve) => setTimeout(resolve, delayMs)).then(() =>
      retryImport(factory, attempts - 1, delayMs),
    );
  });
}
