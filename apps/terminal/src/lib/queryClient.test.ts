import { afterEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('createQueryClient (D-TW-6 breadcrumbs)', () => {
  it('breadcrumbs a failed query with its KEY — the zero-console finding', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const qc = createQueryClient();
    await expect(
      qc.fetchQuery({
        queryKey: ['threads'],
        queryFn: () => Promise.reject(new Error('HTTP 401 on /v1/threads')),
        retry: false,
      }),
    ).rejects.toThrow('HTTP 401');
    expect(spy).toHaveBeenCalledTimes(1);
    expect(String(spy.mock.calls[0]![0])).toContain('["threads"]'); // WHICH read died
    expect((spy.mock.calls[0]![1] as Error).message).toContain('HTTP 401'); // and why
  });

  it('keeps the app`s query defaults (this factory replaced them — it must not drop them)', () => {
    const q = createQueryClient().getDefaultOptions().queries;
    expect(q?.staleTime).toBe(30_000);
    expect(q?.retry).toBe(1);
  });

  it('says nothing on a successful query', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const qc = createQueryClient();
    await qc.fetchQuery({ queryKey: ['profile'], queryFn: () => Promise.resolve({ ok: true }) });
    expect(spy).not.toHaveBeenCalled();
  });
});
