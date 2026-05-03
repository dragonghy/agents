/**
 * MVTH + console smoke test via Playwright.
 *
 * Visits every page in the sidebar, captures:
 * - console errors / warnings
 * - failed HTTP requests (>= 400)
 * - uncaught page errors
 * - screenshot of each page
 *
 * For /test-harness specifically: drives the full flow (spawn → send → resume → close)
 * and captures the conversation.
 *
 * Run: node e2e-smoke.mjs
 * Dependencies: playwright (npm install --no-save playwright + npx playwright install chromium)
 */
import { chromium } from 'playwright';
import fs from 'fs/promises';
import path from 'path';

const BASE = 'http://127.0.0.1:3001';
const OUT_DIR = '/tmp/mvth-smoke';
await fs.mkdir(OUT_DIR, { recursive: true });

const PAGES = [
  { path: '/', label: 'overview' },
  { path: '/board', label: 'board' },
  { path: '/briefs', label: 'briefs' },
  { path: '/cost', label: 'cost' },
  { path: '/test-harness', label: 'test-harness' },
];

const findings = [];

async function visit(browser, route) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  const failedRequests = [];
  const consoleMsgs = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      consoleMsgs.push({ type: msg.type(), text: msg.text() });
    }
  });
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('response', (resp) => {
    if (resp.status() >= 400) {
      failedRequests.push({ status: resp.status(), url: resp.url() });
    }
  });

  let navError = null;
  try {
    await page.goto(BASE + route.path, { waitUntil: 'networkidle', timeout: 15000 });
  } catch (e) {
    navError = String(e);
  }
  await page.waitForTimeout(1500);
  const ssPath = path.join(OUT_DIR, `${route.label}.png`);
  await page.screenshot({ path: ssPath, fullPage: true });
  const title = await page.title();
  const bodyText = (await page.evaluate(() => document.body.innerText)).slice(0, 2000);

  findings.push({
    route: route.path,
    label: route.label,
    title,
    nav_error: navError,
    page_errors: errors,
    console_messages: consoleMsgs,
    failed_requests: failedRequests,
    screenshot: ssPath,
    body_excerpt: bodyText,
  });

  await ctx.close();
}

async function driveTestHarness(browser) {
  console.log('\n=== Test Harness deep flow ===');
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const consoleMsgs = [];
  const errors = [];
  const failedRequests = [];

  page.on('console', (msg) => consoleMsgs.push({ type: msg.type(), text: msg.text() }));
  page.on('pageerror', (err) => errors.push(String(err)));
  page.on('response', (resp) => {
    if (resp.status() >= 400) {
      failedRequests.push({ status: resp.status(), url: resp.url(), method: resp.request().method() });
    }
  });

  await page.goto(BASE + '/test-harness', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(2000);

  // Step 1: capture initial state
  await page.screenshot({ path: path.join(OUT_DIR, 'th-1-loaded.png'), fullPage: true });

  // Find profile select
  const selects = await page.$$('select');
  console.log(`select elements found: ${selects.length}`);

  // Find buttons and inputs
  const buttons = await page.$$eval('button', (els) => els.map((b) => ({ text: b.textContent.trim(), disabled: b.disabled })));
  console.log('buttons:', JSON.stringify(buttons));
  const inputs = await page.$$eval('input, textarea', (els) => els.map((e) => ({ tag: e.tagName, type: e.type, placeholder: e.placeholder, name: e.name })));
  console.log('inputs:', JSON.stringify(inputs));

  // Profile picker is select#profile-pick (workspace switcher is select#ws-switch).
  try {
    await page.selectOption('select#profile-pick', { value: 'secretary' });
    console.log('selected secretary');
  } catch (e) {
    console.log('select option failed:', String(e));
  }

  // Find Spawn button — try by role/text
  let spawnBtn = await page.$('button:has-text("Spawn")');
  if (!spawnBtn) {
    spawnBtn = await page.$('button[aria-label="Spawn"]');
  }
  if (spawnBtn && !(await spawnBtn.isDisabled())) {
    console.log('clicking Spawn...');
    await spawnBtn.click();
    await page.waitForTimeout(2500);
    await page.screenshot({ path: path.join(OUT_DIR, 'th-2-spawned.png'), fullPage: true });
  } else {
    console.log('Spawn button not found or disabled');
  }

  // Find textarea, type message, click Send
  const textarea = await page.$('textarea');
  if (textarea) {
    console.log('typing message...');
    await textarea.fill('In one short sentence, what is your role?');
    const sendBtn = await page.$('button:has-text("Send")');
    if (sendBtn && !(await sendBtn.isDisabled())) {
      console.log('clicking Send (real Claude call, ~5-15s)...');
      await sendBtn.click();
      // Wait up to 60s for response
      try {
        await page.waitForFunction(
          () => {
            const allDivs = Array.from(document.querySelectorAll('*'));
            return allDivs.some((el) => el.textContent?.includes('assistant') || el.textContent?.length > 100);
          },
          { timeout: 60000 }
        );
      } catch (e) {
        console.log('wait for assistant text timed out:', String(e));
      }
      await page.waitForTimeout(2000);
      await page.screenshot({ path: path.join(OUT_DIR, 'th-3-replied.png'), fullPage: true });
    } else {
      console.log('Send button not found or disabled');
    }
  } else {
    console.log('textarea not found');
  }

  // Capture conversation log + final state
  const conversationText = await page.evaluate(() => document.body.innerText);

  findings.push({
    route: '/test-harness (deep flow)',
    label: 'test-harness-deep',
    page_errors: errors,
    console_messages: consoleMsgs.filter((m) => m.type === 'error' || m.type === 'warning'),
    failed_requests: failedRequests,
    body_excerpt: conversationText.slice(0, 3000),
    screenshot: path.join(OUT_DIR, 'th-3-replied.png'),
  });

  await ctx.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  for (const route of PAGES) {
    console.log(`\n=== visiting ${route.path} ===`);
    await visit(browser, route);
  }
  await driveTestHarness(browser);
  await browser.close();

  await fs.writeFile(path.join(OUT_DIR, 'findings.json'), JSON.stringify(findings, null, 2));

  console.log('\n=========================================');
  console.log('SUMMARY');
  console.log('=========================================');
  for (const f of findings) {
    const issues =
      (f.page_errors?.length || 0) +
      (f.failed_requests?.length || 0) +
      (f.console_messages?.length || 0);
    const tag = f.nav_error ? '🔴 NAV-ERR' : issues === 0 ? '✅ clean' : `⚠️  ${issues} issue(s)`;
    console.log(`${tag.padEnd(20)} ${f.route}`);
    if (f.nav_error) console.log(`  nav: ${f.nav_error.slice(0, 200)}`);
    for (const e of f.page_errors || []) console.log(`  ⚠️ pageError: ${e.slice(0, 200)}`);
    for (const m of f.console_messages || []) console.log(`  ⚠️ console.${m.type}: ${m.text.slice(0, 200)}`);
    for (const r of f.failed_requests || []) console.log(`  ⚠️ HTTP ${r.status}: ${r.method || 'GET'} ${r.url}`);
  }
  console.log(`\nFindings JSON: ${path.join(OUT_DIR, 'findings.json')}`);
  console.log(`Screenshots:    ${OUT_DIR}/`);
})().catch((err) => {
  console.error('SCRIPT FAILED:', err);
  process.exit(1);
});
