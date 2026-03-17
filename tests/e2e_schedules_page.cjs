/**
 * E2E test for Scheduled Jobs management page (Ticket #331)
 * Tests: page load, table display, CRUD operations, dark mode, validation
 *
 * Usage: node tests/e2e_schedules_page.cjs
 */
const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:8765';
const SDIR = 'tests/screenshots/331';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  let passed = 0;
  let failed = 0;

  async function check(name, fn) {
    try {
      await fn();
      console.log('PASS:', name);
      passed++;
    } catch (e) {
      console.log('FAIL:', name, '-', e.message.slice(0, 150));
      failed++;
    }
  }

  // Helper: submit React form via SubmitEvent
  async function submitForm() {
    await page.evaluate(() => {
      const form = document.querySelector('form');
      const btn = form.querySelector('button[type="submit"]');
      form.dispatchEvent(new SubmitEvent('submit', {
        bubbles: true, cancelable: true, submitter: btn,
      }));
    });
    await page.waitForTimeout(500);
  }

  // ── Test 1: Page loads with table ──
  await check('1. Page loads with Scheduled Jobs title and 6 table headers', async () => {
    await page.goto(BASE + '/schedules');
    await page.waitForLoadState('networkidle');
    const title = await page.locator('h2').textContent();
    if (!title.includes('Scheduled Jobs')) throw new Error('Title: ' + title);
    const headers = await page.locator('th').allTextContents();
    for (const h of ['Agent', 'Interval', 'Prompt', 'Last Run', 'Created', 'Actions']) {
      if (!headers.includes(h)) throw new Error('Missing header: ' + h);
    }
    await page.screenshot({ path: SDIR + '/01-page-loaded-light.png', fullPage: true });
  });

  // ── Test 2: Existing schedule data ──
  await check('2. Existing schedule shows agent badge, 24h interval, prompt tooltip', async () => {
    const firstRow = page.locator('tbody tr').first();
    const badge = await firstRow.locator('span.rounded-full').textContent();
    if (!badge.includes('product-kevin')) throw new Error('Badge: ' + badge);
    const interval = await firstRow.locator('td:nth-child(2)').textContent();
    if (!interval.includes('24h')) throw new Error('Interval: ' + interval);
    const tooltip = await firstRow.locator('td:nth-child(3) span[title]').getAttribute('title');
    if (!tooltip || tooltip.length < 10) throw new Error('Tooltip missing');
    if (!await firstRow.locator('button:has-text("Delete")').isVisible()) throw new Error('No Delete button');
  });

  // ── Test 3: Sidebar navigation ──
  await check('3. Sidebar has Schedules link', async () => {
    const link = page.locator('nav a[href="/schedules"]');
    if (!await link.isVisible()) throw new Error('Link not visible');
    if (!(await link.textContent()).includes('Schedules')) throw new Error('Wrong text');
    await page.screenshot({ path: SDIR + '/02-sidebar-navigation.png', fullPage: true });
  });

  // ── Test 4: Create form opens, validates, and cancels ──
  await check('4. Create form: opens, validates empty fields, cancels cleanly', async () => {
    await page.goto(BASE + '/schedules');
    await page.waitForLoadState('networkidle');
    await page.click('button:has-text("Create Schedule")');
    await page.waitForTimeout(300);
    if (!await page.locator('form').isVisible()) throw new Error('Form not visible');
    const opts = await page.locator('select option').count();
    if (opts <= 1) throw new Error('No agent options');
    if (!await page.locator('input[type="number"]').isVisible()) throw new Error('No interval input');
    if (!await page.locator('textarea').isVisible()) throw new Error('No textarea');
    await page.screenshot({ path: SDIR + '/03-create-form-open.png', fullPage: true });

    // Validate empty submit
    await submitForm();
    const hasError = await page.evaluate(() => document.body.innerText.includes('All fields are required'));
    if (!hasError) throw new Error('Validation error not shown');
    await page.screenshot({ path: SDIR + '/04-form-validation-error.png', fullPage: true });

    // Cancel
    await page.click('button:has-text("Cancel")');
    if (await page.locator('form').isVisible()) throw new Error('Form still visible');
  });

  // ── Test 5: Full CRUD - create schedule ──
  await check('5. Create new schedule via form and verify in table', async () => {
    await page.goto(BASE + '/schedules');
    await page.waitForLoadState('networkidle');
    const initialCount = await page.locator('tbody tr').count();

    await page.click('button:has-text("Create Schedule")');
    await page.waitForTimeout(300);
    await page.selectOption('select', 'qa-oliver');
    await page.fill('input[type="number"]', '8');
    await page.fill('textarea', 'E2E test schedule — will be deleted');
    await page.screenshot({ path: SDIR + '/05-form-filled.png', fullPage: true });

    await submitForm();
    await page.waitForTimeout(2500);

    const afterCount = await page.locator('tbody tr').count();
    if (afterCount <= initialCount) throw new Error('Row count: ' + initialCount + ' -> ' + afterCount);
    const newRow = page.locator('tbody tr', { hasText: 'qa-oliver' });
    if (!await newRow.isVisible()) throw new Error('qa-oliver row not visible');
    await page.screenshot({ path: SDIR + '/06-after-create.png', fullPage: true });
  });

  // ── Test 6: Delete confirmation - No cancels ──
  await check('6. Delete confirmation — clicking No keeps the row', async () => {
    const row = page.locator('tbody tr', { hasText: 'qa-oliver' });
    await row.locator('button:has-text("Delete")').click();
    await page.waitForTimeout(300);
    if (!await row.locator('text=Delete?').isVisible()) throw new Error('Confirmation not shown');
    if (!await row.locator('button:has-text("Yes")').isVisible()) throw new Error('Yes not shown');
    if (!await row.locator('button:has-text("No")').isVisible()) throw new Error('No not shown');
    await row.locator('button:has-text("No")').click();
    await page.waitForTimeout(300);
    if (!await row.locator('button:has-text("Delete")').isVisible()) throw new Error('Row disappeared');
    await page.screenshot({ path: SDIR + '/07-delete-confirm-no.png', fullPage: true });
  });

  // ── Test 7: Delete confirmation - Yes deletes ──
  await check('7. Delete confirmation — clicking Yes removes the row', async () => {
    const beforeCount = await page.locator('tbody tr').count();
    const row = page.locator('tbody tr', { hasText: 'qa-oliver' });
    await row.locator('button:has-text("Delete")').click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: SDIR + '/08-delete-confirm-yes.png', fullPage: true });
    await row.locator('button:has-text("Yes")').click();
    await page.waitForTimeout(2500);
    const afterCount = await page.locator('tbody tr').count();
    if (afterCount >= beforeCount) throw new Error('Not deleted: ' + beforeCount + ' -> ' + afterCount);
    await page.screenshot({ path: SDIR + '/09-after-delete.png', fullPage: true });
  });

  // ── Test 8: Dark mode ──
  await check('8. Dark mode renders table and form correctly', async () => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto(BASE + '/schedules');
    await page.waitForLoadState('networkidle');
    if (!(await page.locator('h2').textContent()).includes('Scheduled Jobs')) throw new Error('Title missing');
    await page.screenshot({ path: SDIR + '/10-dark-mode-table.png', fullPage: true });
    await page.click('button:has-text("Create Schedule")');
    await page.waitForTimeout(300);
    await page.screenshot({ path: SDIR + '/11-dark-mode-form.png', fullPage: true });
    await page.emulateMedia({ colorScheme: 'light' });
  });

  // ── Test 9: Last Run "Never" ──
  await check('9. Last Run shows "Never" for new schedules (last_dispatched_at=0)', async () => {
    const res = await page.evaluate(async () => {
      const r = await fetch('/api/v1/schedules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: 'qa-oliver', interval_hours: 1, prompt: 'Test Never display' }),
      });
      return r.json();
    });
    await page.goto(BASE + '/schedules');
    await page.waitForLoadState('networkidle');
    const row = page.locator('tbody tr', { hasText: 'Test Never display' });
    const lastRun = await row.locator('td:nth-child(4)').textContent();
    if (lastRun.trim() !== 'Never') throw new Error('Expected "Never", got "' + lastRun.trim() + '"');
    await page.screenshot({ path: SDIR + '/12-never-display.png', fullPage: true });
    await page.evaluate(async (id) => {
      await fetch('/api/v1/schedules/' + id, { method: 'DELETE' });
    }, res.id);
  });

  // ── Test 10: Prompt truncation ──
  await check('10. Prompt column uses CSS truncation with title tooltip', async () => {
    await page.goto(BASE + '/schedules');
    await page.waitForLoadState('networkidle');
    const span = page.locator('tbody tr:first-child td:nth-child(3) span[title]');
    const cls = await span.getAttribute('class');
    if (!cls.includes('truncate')) throw new Error('No truncate class');
    const title = await span.getAttribute('title');
    if (!title || title.length < 20) throw new Error('Tooltip: ' + title);
  });

  console.log('\n' + '='.repeat(50));
  console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed}`);
  console.log('Screenshots saved to: ' + SDIR);
  console.log('='.repeat(50));

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
})();
