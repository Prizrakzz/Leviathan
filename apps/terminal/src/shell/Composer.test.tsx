import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Composer } from './Composer';

// The composer docks the DepthControl, which reads two balances (the dossier allowance, D-DR-3, and the
// credit grant, D-MW-25) -- so it needs a query client and stubbed fetchers. `null` = the routes are dark,
// which is the correct default for a suite that is about the TEXT BOX and has no opinion about either meter.
vi.mock('@/api/dossier', async (orig) => {
  const actual = await orig<typeof import('@/api/dossier')>();
  return { ...actual, getDossierQuota: () => Promise.resolve(null) };
});
vi.mock('@/api/credits', async (orig) => {
  const actual = await orig<typeof import('@/api/credits')>();
  return { ...actual, getCredits: () => Promise.resolve(null) };
});

function mount(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('Composer', () => {
  it('Enter submits + clears; Shift+Enter does not submit', () => {
    const onSubmit = vi.fn();
    mount(<Composer onSubmit={onSubmit} streaming={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'why is wheat tight?' } });
    fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(onSubmit).toHaveBeenCalledWith('why is wheat tight?');
    expect(ta.value).toBe('');
  });

  it('is disabled while streaming and refocuses on completion', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <Composer onSubmit={() => {}} streaming={true} autoFocus={false} />
      </QueryClientProvider>,
    );
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    expect(ta.disabled).toBe(true);
    rerender(
      <QueryClientProvider client={qc}>
        <Composer onSubmit={() => {}} streaming={false} autoFocus={false} />
      </QueryClientProvider>,
    );
    expect(ta.disabled).toBe(false);
    expect(document.activeElement).toBe(ta);
  });

  it('D-TW-5a: a MODIFIED Enter is left to the global hotkey — one keystroke, one turn', () => {
    const onSubmit = vi.fn();
    mount(<Composer onSubmit={onSubmit} streaming={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'why is wheat tight?' } });
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true });
    fireEvent.keyDown(ta, { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(ta.value).toBe('why is wheat tight?'); // and nothing was cleared out from under the user
  });

  it('ignores empty submissions', () => {
    const onSubmit = vi.fn();
    mount(<Composer onSubmit={onSubmit} streaming={false} />);
    const ta = screen.getByTestId('composer') as HTMLTextAreaElement;
    fireEvent.keyDown(ta, { key: 'Enter' });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
