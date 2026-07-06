import { describe, expect, it, vi } from 'vitest';
import { retryImport } from './retryImport';

describe('retryImport (S2.1)', () => {
  it('returns the module on first success without retrying', async () => {
    const factory = vi.fn().mockResolvedValue({ default: 42 });
    await expect(retryImport(factory, 2, 1)).resolves.toEqual({ default: 42 });
    expect(factory).toHaveBeenCalledTimes(1);
  });

  it('retries once after a transient failure, then succeeds', async () => {
    const factory = vi
      .fn()
      .mockRejectedValueOnce(new Error('Failed to fetch dynamically imported module'))
      .mockResolvedValueOnce({ default: 7 });
    await expect(retryImport(factory, 2, 1)).resolves.toEqual({ default: 7 });
    expect(factory).toHaveBeenCalledTimes(2);
  });

  it('propagates the final rejection so the boundary can show (does not swallow)', async () => {
    const factory = vi.fn().mockRejectedValue(new Error('gone'));
    await expect(retryImport(factory, 2, 1)).rejects.toThrow('gone');
    expect(factory).toHaveBeenCalledTimes(2);
  });
});
