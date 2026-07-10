import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useProfile, useUpdateProfile } from '@/api/useProfile';
import { COMMODITIES, SEATS } from '@/lib/commodities';
import { useSettings, type SettingsTab } from '@/store/settings';
import { useUI } from '@/store/ui';
import { ACCENTS, OVERLAY_SCRIM, type AccentName } from '@/tokens/tokens';
import { ChipList, ToggleChip } from './chips';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <div className="mb-2 font-mono text-11 uppercase tracking-wider text-text-dim">{title}</div>
      {children}
    </div>
  );
}

// ── tabs ────────────────────────────────────────────────────────────────────────────────────────────
type Facts = { markets: string[]; regions: string[]; notes: string[]; seat: string };

function factsFrom(raw: unknown): Facts {
  const f = (raw ?? {}) as Record<string, unknown>;
  const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);
  return { markets: list(f.markets), regions: list(f.regions), notes: list(f.notes), seat: typeof f.seat === 'string' ? f.seat : '' };
}

function toPayload(f: Facts): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (f.markets.length) out.markets = f.markets;
  if (f.regions.length) out.regions = f.regions;
  if (f.notes.length) out.notes = f.notes;
  if (f.seat) out.seat = f.seat;
  return out;
}

function ProfileTab() {
  const { data: profile } = useProfile();
  const update = useUpdateProfile();
  const setForceOnboarding = useSettings((s) => s.setForceOnboarding);
  const closeSettings = useSettings((s) => s.closeSettings);
  const open = useSettings((s) => s.open);

  const [draft, setDraft] = useState<Facts>(() => factsFrom(profile?.facts));
  // Seed the editable draft ONCE per open (after the profile is available) — a background profile refetch
  // must not clobber the user's unsaved edits (review finding). seeded resets when the modal closes.
  const seeded = useRef(false);
  useEffect(() => {
    if (!open) {
      seeded.current = false;
      return;
    }
    if (!seeded.current && profile) {
      setDraft(factsFrom(profile.facts));
      seeded.current = true;
    }
  }, [open, profile]);

  // "saved ✓" shows only while the draft still equals what the server has (any further edit clears it).
  const savedClean = useMemo(
    () => JSON.stringify(toPayload(draft)) === JSON.stringify(toPayload(factsFrom(profile?.facts))),
    [draft, profile?.facts],
  );
  const memberSince = profile?.first_seen ? profile.first_seen.slice(0, 10) : '—';

  return (
    <div>
      <div className="flex items-center gap-3 border-b border-line pb-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-bg-2 font-mono text-14 text-cyan">
          {(profile?.name ?? profile?.email ?? 'u')[0]?.toUpperCase()}
        </span>
        <div className="min-w-0">
          <div className="truncate font-sans text-13 text-text">{profile?.name ?? profile?.email ?? 'you'}</div>
          <div className="truncate font-mono text-11 text-text-faint">
            {profile?.email ?? '—'} · member since {memberSince} · {profile?.turn_count ?? 0} turns
          </div>
        </div>
      </div>

      <Section title="Markets you follow">
        <div className="flex flex-wrap gap-1.5">
          {COMMODITIES.map((c) => (
            <ToggleChip
              key={c}
              label={c}
              on={draft.markets.includes(c)}
              onClick={() =>
                setDraft((d) => ({ ...d, markets: d.markets.includes(c) ? d.markets.filter((x) => x !== c) : [...d.markets, c] }))
              }
            />
          ))}
        </div>
      </Section>

      <Section title="Your seat">
        <div className="flex flex-wrap gap-1.5">
          {SEATS.map((s) => (
            <ToggleChip key={s} label={s} on={draft.seat === s} onClick={() => setDraft((d) => ({ ...d, seat: d.seat === s ? '' : s }))} />
          ))}
        </div>
      </Section>

      <Section title="Regions / drivers you watch">
        <ChipList items={draft.regions} onChange={(v) => setDraft((d) => ({ ...d, regions: v }))} placeholder="e.g. Brazil weather — press Enter" />
      </Section>

      <Section title="Notes">
        <ChipList items={draft.notes} onChange={(v) => setDraft((d) => ({ ...d, notes: v }))} placeholder="a short fact about you — press Enter" />
      </Section>

      <div className="mt-5 flex items-center justify-between border-t border-line pt-3">
        <button
          type="button"
          onClick={() => {
            closeSettings();
            setForceOnboarding(true);
          }}
          className="font-mono text-11 text-text-dim hover:text-cyan"
        >
          Redo onboarding
        </button>
        <div className="flex items-center gap-3">
          {update.isSuccess && savedClean && <span className="font-mono text-11 text-pos">saved ✓</span>}
          {update.isError && <span className="font-mono text-11 text-neg">save failed</span>}
          <button
            type="button"
            disabled={update.isPending}
            onClick={() => update.mutate({ facts: toPayload(draft) })}
            className="rounded-chip border border-cyan px-3 py-1 font-mono text-11 text-cyan hover:bg-bg-2 disabled:opacity-50"
          >
            {update.isPending ? 'saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function AppearanceTab() {
  const accent = useUI((s) => s.accent);
  const setAccent = useUI((s) => s.setAccent);
  return (
    <Section title="Accent">
      <p className="mb-2 font-sans text-12 text-text-dim">
        The interactive accent — selection, links, focus, the causal-map highlight. The dark canvas is unchanged.
      </p>
      <div className="flex gap-2">
        {(Object.keys(ACCENTS) as AccentName[]).map((a) => (
          <button
            key={a}
            type="button"
            onClick={() => setAccent(a)}
            aria-pressed={accent === a}
            className={`flex items-center gap-2 rounded-chip border px-3 py-1.5 font-mono text-11 ${
              accent === a ? 'border-cyan text-text' : 'border-line text-text-dim hover:border-text-faint'
            }`}
          >
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: ACCENTS[a] }} />
            {a}
            {accent === a && <span className="text-cyan">✓</span>}
          </button>
        ))}
      </div>
    </Section>
  );
}

// ── modal ───────────────────────────────────────────────────────────────────────────────────────────
export default function SettingsModal() {
  const open = useSettings((s) => s.open);
  const tab = useSettings((s) => s.tab);
  const closeSettings = useSettings((s) => s.closeSettings);
  const setTab = (t: SettingsTab) => useSettings.setState({ tab: t });

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && closeSettings()}>
      <Dialog.Portal>
        <Dialog.Overlay className={`fixed inset-0 z-40 ${OVERLAY_SCRIM}`} />
        <Dialog.Content
          data-testid="settings"
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[80vh] w-[560px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-panel border border-line bg-bg-1 shadow-lg"
        >
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <Dialog.Title className="font-mono text-12 uppercase tracking-wider text-text">Settings</Dialog.Title>
            <Dialog.Close aria-label="close settings" className="font-mono text-11 text-text-faint hover:text-cyan">
              esc
            </Dialog.Close>
          </div>
          <div className="flex gap-1 border-b border-line px-4 pt-2">
            {(['profile', 'appearance'] as SettingsTab[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`-mb-px border-b-2 px-2 pb-2 font-mono text-11 uppercase tracking-wider ${
                  tab === t ? 'border-cyan text-text' : 'border-transparent text-text-faint hover:text-text-dim'
                }`}
              >
                {t === 'profile' ? 'Profile & facts' : 'Appearance'}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-4 pb-4 pt-1">
            {tab === 'profile' ? <ProfileTab /> : <AppearanceTab />}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
