import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useAuth } from 'react-oidc-context';
import { listNotifications, markNotificationSeen } from '@/api/client';
import type { NotificationItem } from '@/api/schema';
import { authEnabled } from '@/auth/oidc';
import { useAsOf } from '@/store/asof';
import { useUI } from '@/store/ui';

interface Props {
  /** The controlled CommandBar state setter (threaded Shell → TopBar → here). Row-click PREFILLS it. */
  setCmd: (v: string) => void;
}

/**
 * P3 Track D — the daily-digest notification bell in the top bar. Auth-gated (renders and polls only when
 * signed in) and self-contained: a row-click projects the item into a TYPED P2 event chip and prefills the
 * composer (never auto-submits), then marks the item read so the badge drops.
 *
 * Auth is consumed exactly like UserMenu: react-oidc-context's `useAuth()` needs an AuthProvider, which
 * mock/local builds don't mount (App.tsx OpenApp). So the provider-touching path lives behind `authEnabled`;
 * the open shell renders the bell as authenticated (so VITE_MOCK=1 shows it).
 */
export function NotificationBell({ setCmd }: Props) {
  if (!authEnabled) return <BellPopover setCmd={setCmd} />;
  return <AuthedBell setCmd={setCmd} />;
}

function AuthedBell({ setCmd }: Props) {
  const auth = useAuth();
  if (!auth.isAuthenticated) return null; // never render — and never poll — unauthenticated
  return <BellPopover setCmd={setCmd} />;
}

function BellIcon() {
  return (
    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" role="img" aria-hidden="true">
      <path
        d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13.7 21a2 2 0 0 1-3.4 0"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Rendered only when authenticated (or in the open/mock shell), so the poll never runs signed-out. */
function BellPopover({ setCmd }: Props) {
  const qc = useQueryClient();
  const asof = useAsOf((s) => s.asof);
  const [open, setOpen] = useState(false);
  const [pitBlocked, setPitBlocked] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const q = useQuery({
    queryKey: ['notifications'],
    queryFn: listNotifications,
    // 5-MINUTE poll: this is a DAILY digest (the ratified 60s → 5min decision). Never poll on focus.
    refetchInterval: 300_000,
    refetchOnWindowFocus: false,
  });
  const items = q.data ?? [];
  const unseen = items.filter((n) => !n.seen).length;
  const sorted = [...items].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')); // newest-first

  // Outside-click closes the dropdown (UserMenu convention).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const onRow = async (n: NotificationItem) => {
    // PIT guard: a future-dated event can't be attached at the current knowledge horizon — nudge the as-of
    // forward instead of silently attaching something the model can't yet see. DO NOT attach/prefill/mark.
    if (asof && n.date && n.date > asof) {
      setPitBlocked(n.notif_id);
      return;
    }
    // TYPED projection ONLY — never spread `n`; headline/url/driver_id never reach the wire (injection
    // posture: the backend code-maps the driver from event_type, ignoring any client-supplied driver).
    useUI.getState().addChip({
      type: 'event',
      event_type: n.event_type,
      commodity: n.commodity,
      date: n.date,
      summary: n.summary,
      country: n.country,
      label: n.label,
    });
    setCmd(n.query); // PREFILL the composer — never submit
    setPitBlocked(null);
    setOpen(false); // close FIRST: the visible response to the click must not wait on the network

    // D-TW-11: AWAIT the write, THEN invalidate. Fire-and-forget raced the refetch it triggered -- the
    // refetch usually won, re-read the row as still-unseen, and the badge kept its count until the next
    // 5-minute poll. Never silent either: a rejected mark-seen is exactly how a badge sticks with nothing
    // on screen to explain it (D-TW-6 breadcrumb).
    try {
      await markNotificationSeen(n.notif_id);
    } catch (e: unknown) {
      console.error('[notifications] mark-seen failed:', e);
    }
    // Invalidate on BOTH paths: on success it drops the item from the unseen badge, and on failure it
    // reconciles against what the server actually recorded (a lost response is not a lost write).
    void qc.invalidateQueries({ queryKey: ['notifications'] });
  };

  return (
    <div className="relative" ref={ref}>
      <button
        aria-label={unseen ? `notifications (${unseen} unread)` : 'notifications'}
        className="relative flex items-center text-text-dim hover:text-cyan"
        onClick={() => setOpen((o) => !o)}
      >
        <BellIcon />
        {unseen > 0 && (
          <span
            data-testid="notif-badge"
            className="absolute -right-1.5 -top-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-chip bg-amber px-1 font-mono text-11 leading-none text-bg-0"
          >
            {unseen}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-30 max-h-[420px] w-80 overflow-y-auto rounded-panel border border-line bg-bg-1 p-2 shadow-lg">
          <div className="px-2 pb-1 font-mono text-11 uppercase tracking-wider text-text-faint">alerts</div>
          {sorted.length === 0 ? (
            <div className="px-2 py-3 font-sans text-12 text-text-dim">
              {q.isLoading ? 'loading…' : 'no new alerts'}
            </div>
          ) : (
            sorted.map((n) => (
              <button
                key={n.notif_id}
                onClick={() => void onRow(n)}
                className="mt-1 w-full rounded-chip border border-line px-2 py-1.5 text-left hover:border-cyan"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-11 text-cyan">⚡</span>
                  <span className="flex-1 truncate font-sans text-12 text-text">{n.label}</span>
                  {!n.seen && <span className="h-1.5 w-1.5 rounded-chip bg-amber" aria-hidden="true" />}
                </div>
                {n.summary && (
                  <div className="mt-0.5 truncate font-sans text-11 text-text-dim">{n.summary}</div>
                )}
                <div className="mt-0.5 font-mono text-11 text-text-faint">
                  {n.commodity}
                  {n.date ? ` · ${n.date}` : ''}
                </div>
                {pitBlocked === n.notif_id && (
                  <div className="mt-1 font-mono text-11 text-warn">
                    move the as-of forward to include this
                  </div>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
