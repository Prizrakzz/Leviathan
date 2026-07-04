import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { isAuthed } from './auth';
import { Landing } from './landing/Landing';

// The landing gate and terminal are ONE app; the terminal is lazy-loaded behind the (stub) auth gate (§7).
const Terminal = lazy(() => import('./shell/Terminal'));

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route
        path="/app"
        element={
          isAuthed() ? (
            <Suspense
              fallback={<div className="p-6 font-mono text-12 text-text-dim">loading terminal…</div>}
            >
              <Terminal />
            </Suspense>
          ) : (
            <Navigate to="/?signin=1" replace />
          )
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
