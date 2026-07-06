import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const suggestMock = vi.fn();
vi.mock('@/api/client', () => ({ suggest: (p: unknown) => suggestMock(p) }));

import { EmptyState } from './EmptyState';

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EmptyState onAsk={() => {}} />
    </QueryClientProvider>,
  );
}

describe('EmptyState starters (6.2)', () => {
  it('shows the static fallback while loading, then swaps in fetched news-aware starters', async () => {
    let resolve!: (v: { suggestions: string[] }) => void;
    suggestMock.mockReturnValue(new Promise((r) => (resolve = r)));
    mount();
    // fallback renders immediately (never an empty panel)
    expect(screen.getByText(/KC arabica frost in Brazil/)).toBeTruthy();
    resolve({ suggestions: ['Fresh starter about the frost headlines?'] });
    await waitFor(() => expect(screen.getByText('Fresh starter about the frost headlines?')).toBeTruthy());
    expect(screen.queryByText(/KC arabica frost in Brazil/)).toBeNull();
    expect(suggestMock).toHaveBeenCalledWith({ contracts: [] }); // thread-start = the empty packet
  });

  it('keeps the fallback when the suggester errors or returns empty', async () => {
    suggestMock.mockRejectedValue(new Error('down'));
    mount();
    await waitFor(() => expect(screen.getByText(/KC arabica frost in Brazil/)).toBeTruthy());
  });
});
