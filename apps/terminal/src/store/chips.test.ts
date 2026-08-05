import { beforeEach, describe, expect, it } from 'vitest';
import { MAX_ATTACH, toContext } from './chips';
import { useThread } from './thread';
import { useUI } from './ui';

const node = (driver: string) =>
  ({ type: 'node', contract: 'corn', driver_id: driver, label: driver }) as const;

describe('context chips slice (P2 — ephemeral, capped, thread-scoped)', () => {
  beforeEach(() => {
    useUI.getState().clearChips();
  });

  it('add dedupes by key and hard-caps at MAX_ATTACH', () => {
    useUI.getState().addChip(node('drought'));
    useUI.getState().addChip(node('drought')); // dupe -> noop
    expect(useUI.getState().attachedChips).toHaveLength(1);
    for (let i = 0; i < MAX_ATTACH + 2; i++) useUI.getState().addChip(node(`d${i}`));
    expect(useUI.getState().attachedChips).toHaveLength(MAX_ATTACH);
  });

  it('remove by key; toContext strips display-only fields for the wire', () => {
    useUI.getState().addChip(node('drought'));
    useUI.getState().addChip({ type: 'edge', contract: 'corn', source: 'a', target: 'b', label: 'a → b' });
    const chips = useUI.getState().attachedChips;
    useUI.getState().removeChip(chips[0]!.key);
    expect(useUI.getState().attachedChips).toHaveLength(1);
    const wire = toContext(useUI.getState().attachedChips);
    expect(wire[0]).toEqual({ type: 'edge', contract: 'corn', source: 'a', target: 'b' }); // no key/label
  });

  it('a thread switch clears the chips (the thread is the context boundary)', () => {
    useUI.getState().addChip(node('drought'));
    expect(useUI.getState().attachedChips).toHaveLength(1);
    useThread.getState().newThread();
    expect(useUI.getState().attachedChips).toHaveLength(0);
  });

  it('chips are NOT persisted (absent from the lv-ui blob; v5 untouched)', () => {
    useUI.getState().addChip(node('drought'));
    const blob = JSON.parse(localStorage.getItem('lv-ui') ?? '{}');
    expect(blob.version).toBe(5); // D-TW-15 bumped it to drop the dead `view` key
    expect('attachedChips' in (blob.state ?? {})).toBe(false);
  });
});
