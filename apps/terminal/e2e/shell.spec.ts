import { expect, test } from '@playwright/test';

// The Phase-2 gate: the shell is fully keyboard-operable, driven by the mock (VITE_MOCK=1 in the webServer).
test('shell is keyboard-operable and streams a mocked turn', async ({ page }) => {
  await page.goto('/app');

  // command bar is reachable and takes a query
  const cmd = page.getByRole('textbox', { name: 'command' });
  await expect(cmd).toBeVisible();
  await cmd.fill('KC frost 2021');
  await cmd.press('Enter');

  // the staged pipeline appears, then the assembled Answer view (mock ~ <1s)
  await expect(page.getByTestId('pipeline')).toBeVisible();
  await expect(page.getByTestId('note')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('dag')).toBeVisible(); // the live cascade DAG rendered
  await expect(page.getByTestId('numbers')).toBeVisible();
  await expect(page.getByText('INTEGRITY', { exact: false })).toBeVisible();

  // blur the command bar, then `e` opens the receipts drawer, Escape closes it
  await page.getByTestId('note').click();
  await page.keyboard.press('e');
  await expect(page.getByTestId('receipts')).toBeVisible();
  await expect(page.getByText('cited', { exact: false }).first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('receipts')).toBeHidden();

  // ⌘K opens the palette (a global combo — works even from the command bar), Escape closes it
  await page.keyboard.press('ControlOrMeta+k');
  await expect(page.getByTestId('palette')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('palette')).toBeHidden();

  // move focus out of the command bar so single-key hotkeys are active (they are suppressed while typing)
  await page.getByTestId('view').click();

  // ‹/› step the as-of off live -> BACKTEST pill
  await page.keyboard.press(',');
  await expect(page.getByRole('button', { name: 'return to live' })).toBeVisible();

  // ? opens the shortcut sheet
  await page.keyboard.press('?');
  await expect(page.getByTestId('shortcuts')).toBeVisible();
});

// 6.5: a cited receipts row carries a "pdf" affordance that opens the source in the lazy pdf.js modal.
// The mock resolves a data-url doc (an empty-doc-safe value), so we assert the modal MOUNTS — the page
// raster itself is a browser concern, not part of this wiring smoke.
test('a receipts row opens the source PDF in the pdf.js modal', async ({ page }) => {
  await page.goto('/app');
  const cmd = page.getByRole('textbox', { name: 'command' });
  await cmd.fill('KC frost 2021');
  await cmd.press('Enter');

  await expect(page.getByTestId('note')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('note').click(); // blur the command bar so `e` is a hotkey
  await page.keyboard.press('e');
  await expect(page.getByTestId('receipts')).toBeVisible();

  // the first cited row (it carries a source_key) exposes the pdf affordance → the modal mounts lazily
  await page.getByRole('button', { name: /pdf/i }).first().click();
  await expect(page.getByTestId('pdf')).toBeVisible();
  await page.getByRole('button', { name: 'close pdf' }).click();
  await expect(page.getByTestId('pdf')).toBeHidden();
});
