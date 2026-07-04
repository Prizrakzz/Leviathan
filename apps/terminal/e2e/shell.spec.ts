import { expect, test } from '@playwright/test';

// The Phase-2 gate: the shell is fully keyboard-operable, driven by the mock (VITE_MOCK=1 in the webServer).
test('shell is keyboard-operable and streams a mocked turn', async ({ page }) => {
  await page.goto('/app');

  // command bar is reachable and takes a query
  const cmd = page.getByRole('textbox', { name: 'command' });
  await expect(cmd).toBeVisible();
  await cmd.fill('KC frost 2021');
  await cmd.press('Enter');

  // the staged pipeline appears, then the streamed note (mock ~ <1s)
  await expect(page.getByTestId('pipeline')).toBeVisible();
  await expect(page.getByText('INTEGRITY', { exact: false })).toBeVisible({ timeout: 15_000 });

  // ⌘K opens the palette (a global combo — works even from the command bar), Escape closes it
  await page.keyboard.press('ControlOrMeta+k');
  await expect(page.getByTestId('palette')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('palette')).toBeHidden();

  // move focus out of the command bar so single-key hotkeys are active (they are suppressed while typing)
  await page.getByTestId('view').click();

  // g c switches to the convergence view
  await page.keyboard.press('g');
  await page.keyboard.press('c');
  await expect(page.getByTestId('view')).toHaveAttribute('data-view', 'convergence');

  // ‹/› step the as-of off live -> BACKTEST pill
  await page.keyboard.press(',');
  await expect(page.getByRole('button', { name: 'return to live' })).toBeVisible();

  // ? opens the shortcut sheet
  await page.keyboard.press('?');
  await expect(page.getByTestId('shortcuts')).toBeVisible();
});
