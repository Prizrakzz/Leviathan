import { useEffect, useRef, useState } from 'react';
import { useAuth } from 'react-oidc-context';
import { authEnabled, userManager } from '@/auth/oidc';
import { useSettings } from '@/store/settings';

/** The signed-in user (5.6 W1): real name + Google avatar from the ID-token profile claims (Cognito maps
 *  name/given_name/picture from Google; they populate at each user's next sign-in — email local-part is
 *  the fallback until then), with a Settings entry (6.6) + sign-out dropdown. Mock/local builds (no
 *  AuthProvider) keep a stub that still opens Settings, so the UI is fully exercisable without a backend. */
export function UserMenu() {
  if (!authEnabled)
    return (
      <button
        aria-label="user menu"
        onClick={() => useSettings.getState().openSettings('profile')}
        className="font-mono text-12 text-text-dim hover:text-text"
      >
        user ▾
      </button>
    );
  return <AuthedUserMenu />;
}

async function signOut(): Promise<void> {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined;
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
  try {
    await userManager?.removeUser();
  } catch {
    /* local state only — safe to continue */
  }
  if (domain && clientId) {
    // Hosted-UI logout ends the COGNITO session too (else the next "sign in" silently re-auths).
    const uri = encodeURIComponent(window.location.origin);
    window.location.href = `https://${domain}/logout?client_id=${clientId}&logout_uri=${uri}`;
  } else {
    window.location.href = '/';
  }
}

function AuthedUserMenu() {
  const auth = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const p = (auth.user?.profile ?? {}) as {
    name?: string;
    given_name?: string;
    email?: string;
    picture?: string;
  };
  const label = p.name ?? p.given_name ?? p.email?.split('@')[0] ?? 'user';
  const initial = (label[0] ?? 'u').toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        aria-label="user menu"
        className="flex items-center gap-1.5 font-mono text-12 text-text-dim hover:text-text"
        onClick={() => setOpen((o) => !o)}
      >
        {p.picture ? (
          <img src={p.picture} alt="" referrerPolicy="no-referrer" className="h-5 w-5 rounded-full" />
        ) : (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-bg-2 text-11 text-cyan">
            {initial}
          </span>
        )}
        <span className="max-w-[140px] truncate">{label}</span> ▾
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-30 w-56 rounded-panel border border-line bg-bg-1 p-2 shadow-lg">
          <div className="truncate px-2 py-1 font-sans text-12 text-text">{p.name ?? label}</div>
          {p.email && <div className="truncate px-2 pb-1 font-mono text-11 text-text-faint">{p.email}</div>}
          <button
            className="mt-1 w-full rounded-chip border border-line px-2 py-1 text-left font-mono text-12 text-text-dim hover:border-cyan hover:text-cyan"
            onClick={() => {
              setOpen(false);
              useSettings.getState().openSettings('profile');
            }}
          >
            settings
          </button>
          <button
            className="mt-1 w-full rounded-chip border border-line px-2 py-1 text-left font-mono text-12 text-text-dim hover:border-neg hover:text-neg"
            onClick={() => void signOut()}
          >
            sign out
          </button>
        </div>
      )}
    </div>
  );
}
