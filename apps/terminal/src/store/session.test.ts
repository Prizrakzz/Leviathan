import { describe, expect, it } from 'vitest';
import { useSession } from './session';

describe('useSession', () => {
  it('defaults ready=true when auth is disabled (test env has no VITE_COGNITO_*)', () => {
    expect(useSession.getState().ready).toBe(true);
  });
  it('setReady toggles', () => {
    useSession.getState().setReady(false);
    expect(useSession.getState().ready).toBe(false);
    useSession.getState().setReady(true);
    expect(useSession.getState().ready).toBe(true);
  });
});
