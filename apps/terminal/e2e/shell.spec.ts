import { expect, test, type Page } from '@playwright/test';

/**
 * D-TW-19: seed BROWSER STATE before the app boots -- never click the shell into a testable position.
 * Two preconditions have to hold before a single assertion below is meaningful, and both are load-time:
 *
 *  - the first-run onboarding modal must not mount. It is a Radix MODAL dialog (scrim + focus trap +
 *    aria-hidden on the rest of the app), so while it is up the command bar is unreachable -- and it opens
 *    ~120ms after load, exactly late enough to race a dismiss-by-clicking step. `lv-mock-onboarded` makes
 *    the mock profile report itself onboarded (api/mock.ts), so the modal never mounts at all.
 *  - `lv-debug` must exist before any app script runs: AnswerView reads it ONCE at MODULE scope
 *    (SHOW_INTEGRITY), so a localStorage write issued after navigation lands too late to be seen.
 *
 * addInitScript runs on every document ahead of page scripts, which satisfies both.
 */
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('lv-debug', '1'); // AnswerView gates the INTEGRITY strip on this (read at module scope)
    localStorage.setItem('lv-mock-onboarded', '1'); // mock profile seed -- no first-run modal, no focus trap
  });
});

/** Ask the canned mock question and wait for the assembled answer. Shared by both specs. */
async function askAndSettle(page: Page) {
  await page.goto('/app');

  // command bar is reachable and takes a query
  const cmd = page.getByRole('textbox', { name: 'command' });
  await expect(cmd).toBeVisible();
  await cmd.fill('KC frost 2021');
  await cmd.press('Enter');

  // the staged pipeline appears, then the assembled Answer view (mock ~ <1s)
  await expect(page.getByTestId('pipeline')).toBeVisible();
  await expect(page.getByTestId('note')).toBeVisible({ timeout: 15_000 });

  // the seed held. Asserted HERE, seconds past the 120ms profile fetch that would have opened the modal --
  // so a broken seed fails on this line instead of as an unexplained click timeout further down.
  await expect(page.getByTestId('onboarding')).toHaveCount(0);

  // Settle means the TURN IS OVER, not merely "the note element exists" -- the note mounts while synthesis
  // is still streaming, so returning on its visibility alone hands back a page whose focus is still moving.
  // The Composer refocuses ITSELF the moment streaming flips false (Composer.tsx:27, so the next question
  // needs zero mouse work). Both specs then blur the command bar by clicking the note and press a
  // single-key hotkey (`e`). If the turn happened to finish in the gap between that click and the
  // keypress, the composer pulled focus into a TEXTAREA, `isTyping()` suppressed the hotkey
  // (useHotkeys.ts:24), the drawer never opened, and the spec failed on the `receipts` assert -- about 1
  // run in 8 locally, and far more often under load (a traced 2-worker stress failed 6 of 12). The
  // composer is disabled for exactly the streaming window, so waiting for it to be ENABLED is the
  // turn-complete signal. But enabled is NOT settled: the refocus is an EFFECT queued on that same
  // transition, so a click issued between the enable and the effect still gets its focus stolen a
  // tick later (the 2026-08-05 gate refusal -- the 1-in-8 race survived the enabled-wait at lower
  // probability). The refocus itself is the completion signal, so wait for FOCUS, not enablement.
  await expect(page.getByTestId('composer')).toBeEnabled();
  await expect(page.getByTestId('composer')).toBeFocused();
}

/** Blur the command bar/composer so single-key hotkeys are live, deterministically: the refocus
 *  effect has already fired (askAndSettle waited for it), so after this click nothing steals focus
 *  back -- and the not-focused assert makes a future regression fail HERE, named, instead of as a
 *  mystery timeout on whatever hotkey assert comes next. */
async function blurIntoNote(page: Page) {
  await page.getByTestId('note').click();
  await expect(page.getByTestId('composer')).not.toBeFocused();
}

// The Phase-2 gate: the shell is fully keyboard-operable, driven by the mock (VITE_MOCK=1 in the webServer).
test('shell is keyboard-operable and streams a mocked turn', async ({ page }) => {
  await askAndSettle(page);
  await expect(page.getByTestId('numbers')).toBeVisible();
  // The INTEGRITY strip is debug-only (6.1) -- it is on screen BECAUSE of the lv-debug seed above.
  await expect(page.getByTestId('integrity')).toContainText('INTEGRITY');

  // blur the command bar, then `e` opens the receipts drawer, Escape closes it
  await blurIntoNote(page);
  await page.keyboard.press('e');
  await expect(page.getByTestId('receipts')).toBeVisible();
  await expect(page.getByText('cited', { exact: false }).first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('receipts')).toBeHidden();

  // D-TW-19: the answer column stopped rendering the DAG inline at P1.5 (the graph became a workspace TAB
  // because the double render read as a bug), so the old in-column `dag` assert could never pass again.
  // The live equivalent is the chip's whole flow: open causal graph -> a tab appears -> the map renders
  // full-surface inside it.
  await page.getByTestId('open-full-graph').click();
  await expect(page.getByTestId('tab-strip')).toBeVisible();
  await expect(page.getByTestId('graph-tab')).toBeVisible();
  await expect(page.getByTestId('dag')).toBeVisible();

  // (D-TW-14b: the mod+K palette leg lived here. The palette had zero commands and was deleted; Phase 3
  // rebuilds it, and this spec gets the binding back with it.)

  // Focus is on the chip just clicked -- not a text field -- so the single-key bindings are live (they are
  // suppressed while typing). `,` steps the as-of off live -> BACKTEST pill; `?` opens the shortcut sheet.
  await page.keyboard.press(',');
  await expect(page.getByRole('button', { name: 'return to live' })).toBeVisible();
  await page.keyboard.press('?');
  await expect(page.getByTestId('shortcuts')).toBeVisible();
});

// 6.5 / P1.5: a cited receipts row carries a "pdf" affordance that opens the source as a WORKSPACE TAB.
// The mock resolves a 1-page data: URL doc, so this asserts the wiring MOUNTS -- the page raster itself is
// a browser concern, not part of this smoke.
test('a receipts row opens the source PDF as a workspace tab', async ({ page }) => {
  await askAndSettle(page);
  await blurIntoNote(page); // blur the command bar so `e` is a hotkey
  await page.keyboard.press('e');
  await expect(page.getByTestId('receipts')).toBeVisible();

  // the first cited row (it carries a source_key) exposes the pdf affordance
  await page.getByTestId('receipts').getByRole('button', { name: /pdf/i }).first().click();

  // Close the drawer before touching the workspace: it is a MODAL dialog, so its scrim would swallow the
  // tab-strip click below (the tab itself opened behind it, which is the P1.5 shape).
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('receipts')).toBeHidden();

  // D-TW-19: `pdf` / `close pdf` were the 6.5 MODAL's ids and both are gone -- P1.5 replaced the modal with
  // a tab, so the surface id is the viewer's own (`pdf-viewer`) and closing is the TabStrip's per-tab button.
  await expect(page.getByTestId('pdf-tab')).toBeVisible();
  await expect(page.getByTestId('pdf-viewer')).toBeVisible();

  await page
    .getByRole('tablist', { name: 'open documents' })
    .getByRole('button', { name: /^close / })
    .click();
  // Last tab closed -> the whole document area folds away (zero tabs = the chat panel owns the height).
  await expect(page.getByTestId('pdf-viewer')).toHaveCount(0);
  await expect(page.getByTestId('tab-strip')).toHaveCount(0);
});
