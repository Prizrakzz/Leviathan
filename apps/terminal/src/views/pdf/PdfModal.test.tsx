import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePdf } from '@/store/pdf';

// The client is mocked so we drive the resolved {url,page,...} directly; pdf.js is mocked because jsdom has
// no real canvas 2d context (the render path is exercised in the e2e chromium run, not here).
const { getPdfPage } = vi.hoisted(() => ({ getPdfPage: vi.fn() }));
vi.mock('@/api/client', () => ({ getPdfPage }));

const { getDocument } = vi.hoisted(() => {
  const page = { getViewport: () => ({ width: 120, height: 160 }), render: () => ({ promise: Promise.resolve() }) };
  const doc = { numPages: 3, getPage: () => Promise.resolve(page), destroy: () => Promise.resolve() };
  return { getDocument: vi.fn(() => ({ promise: Promise.resolve(doc) })) };
});
vi.mock('pdfjs-dist', () => ({ GlobalWorkerOptions: {}, getDocument, version: 'mock' }));

import PdfModal from './PdfModal';

describe('PdfModal (6.5 click-to-page)', () => {
  beforeEach(() => {
    getPdfPage.mockReset();
    getDocument.mockClear();
    usePdf.setState({ open: true, sourceKey: 's3://gain/x', snippet: 'frost', charStart: undefined, offsetKind: undefined });
  });

  it('resolves with the doc-locator args and opens at the resolved page', async () => {
    getPdfPage.mockResolvedValue({ url: 'data:application/pdf;base64,', page: 2, kind: 'pdf', expires_in: 900 });
    render(<PdfModal />);
    expect(await screen.findByText('p 2 / 3')).toBeInTheDocument();
    expect(getPdfPage).toHaveBeenCalledWith('s3://gain/x', 'frost', undefined, undefined);
  });

  it('opens at page 1 and shows the page-unknown banner when page is null', async () => {
    getPdfPage.mockResolvedValue({ url: 'data:application/pdf;base64,', page: null, kind: 'pdf', expires_in: 900 });
    render(<PdfModal />);
    expect(await screen.findByText(/page unknown/i)).toBeInTheDocument();
    expect(await screen.findByText('p 1 / 3')).toBeInTheDocument();
  });

  it('prev/next step the page and clamp at the bounds', async () => {
    getPdfPage.mockResolvedValue({ url: 'data:application/pdf;base64,', page: 2, kind: 'pdf', expires_in: 900 });
    render(<PdfModal />);
    await screen.findByText('p 2 / 3');
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(await screen.findByText('p 3 / 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled(); // clamped at the last page
    fireEvent.click(screen.getByRole('button', { name: /prev/i }));
    expect(await screen.findByText('p 2 / 3')).toBeInTheDocument();
  });

  it('closes through the store (the lazy mount unmounts on open=false)', async () => {
    getPdfPage.mockResolvedValue({ url: 'data:application/pdf;base64,', page: 2, kind: 'pdf', expires_in: 900 });
    render(<PdfModal />);
    await screen.findByText('p 2 / 3');
    fireEvent.click(screen.getByLabelText('close pdf'));
    await waitFor(() => expect(usePdf.getState().open).toBe(false));
  });

  it('keeps the raw-download escape when the document fails to load (never a blank modal)', async () => {
    getPdfPage.mockResolvedValue({ url: 'data:application/pdf;base64,BAD', page: 1, kind: 'pdf', expires_in: 900 });
    getDocument.mockImplementationOnce(() => ({ promise: Promise.reject(new Error('bad pdf')) }));
    render(<PdfModal />);
    expect(await screen.findByText(/load this document/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /download the raw file/i })).toBeInTheDocument();
  });
});
