import { create } from 'zustand';

export type SettingsTab = 'profile' | 'appearance';

/**
 * Settings-modal + onboarding UI state (6.6) — ephemeral (not persisted). `open`/`tab` drive the Settings
 * dialog; `forceOnboarding` lets the "Redo onboarding" button re-open the first-run flow even after the
 * profile is already onboarded (the gate normally keys off `profile.onboarded`).
 */
export interface SettingsState {
  open: boolean;
  tab: SettingsTab;
  forceOnboarding: boolean;
  openSettings: (tab?: SettingsTab) => void;
  closeSettings: () => void;
  setForceOnboarding: (v: boolean) => void;
}

export const useSettings = create<SettingsState>((set) => ({
  open: false,
  tab: 'profile',
  forceOnboarding: false,
  openSettings: (tab = 'profile') => set({ open: true, tab }),
  closeSettings: () => set({ open: false }),
  setForceOnboarding: (v) => set({ forceOnboarding: v }),
}));
