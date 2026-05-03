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
  { path: '/sessions', label: 'sessions' },
  { path: '/profiles', label: 'profiles' },
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

  // Open an SSE listener inside the page that captures every
  // session.message_appended event the daemon publishes during this
  // test. We assert later that we saw at least one for the session we
  // spawn — that proves the live-streaming loop works end-to-end.
  await page.evaluate(() => {
    const w = window;
    w.__sseEvents = [];
    try {
      const es = new EventSource('/api/v1/orchestration/events');
      ['session.created', 'session.message_appended', 'session.cost_updated', 'session.closed'].forEach((kind) => {
        es.addEventListener(kind, (ev) => {
          try {
            const parsed = JSON.parse(ev.data);
            w.__sseEvents.push(parsed);
          } catch (err) {
            console.warn('bad SSE frame', err);
          }
        });
      });
      w.__sseEs = es;
    } catch (err) {
      console.warn('EventSource construction failed:', err);
    }
  });

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

  // SSE assertion: did the in-page EventSource see a message_appended
  // event? If yes, the live-streaming loop works end-to-end. We tolerate
  // up to ~5s of arrival latency past the LLM reply to absorb network
  // jitter in CI.
  await page.waitForTimeout(5000);
  const sseSummary = await page.evaluate(() => {
    const w = window;
    const events = w.__sseEvents || [];
    const kinds = events.map((e) => e.kind || e.event || 'unknown');
    return {
      total: events.length,
      kinds,
      saw_message_appended: kinds.includes('session.message_appended'),
      saw_session_created: kinds.includes('session.created'),
    };
  });
  console.log('SSE summary:', JSON.stringify(sseSummary));
  const sseAssertions = [];
  if (!sseSummary.saw_message_appended) {
    sseAssertions.push(
      'expected at least one session.message_appended SSE event during the test, got 0'
    );
  }

  findings.push({
    route: '/test-harness (deep flow)',
    label: 'test-harness-deep',
    page_errors: [...errors, ...sseAssertions],
    console_messages: consoleMsgs.filter((m) => m.type === 'error' || m.type === 'warning'),
    failed_requests: failedRequests,
    body_excerpt: conversationText.slice(0, 3000),
    screenshot: path.join(OUT_DIR, 'th-3-replied.png'),
    sse_summary: sseSummary,
  });

  await ctx.close();
}

async function driveProfileDetail(browser) {
  console.log('\n=== Profile detail walk ===');
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

  await page.goto(BASE + '/profiles', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(1500);
  const link = await page.$('a[href^="/profiles/"]');
  if (link) {
    await link.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(OUT_DIR, 'profile-detail.png'), fullPage: true });
  } else {
    console.log('No profile cards to drill into.');
  }

  findings.push({
    route: '/profiles/:name (drill-in)',
    label: 'profiles-drill',
    page_errors: errors,
    console_messages: consoleMsgs,
    failed_requests: failedRequests,
    screenshot: path.join(OUT_DIR, 'profile-detail.png'),
  });
  await ctx.close();
}

async function driveTicketDetail(browser) {
  console.log('\n=== Tickets detail walk ===');
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

  // Pull a ticket id from the API (whichever live ticket comes first).
  let ticketId = null;
  try {
    const r = await fetch(`${BASE}/api/v1/orchestration/tickets?limit=1`);
    if (r.ok) {
      const body = await r.json();
      if (body.tickets?.length > 0) ticketId = body.tickets[0].id;
    }
  } catch (e) {
    console.log('ticket id fetch failed:', String(e));
  }

  if (ticketId == null) {
    // Fallback: try board endpoint.
    try {
      const r = await fetch(`${BASE}/api/tickets/board`);
      if (r.ok) {
        const body = await r.json();
        for (const col of body.columns || []) {
          if (col.tickets?.length > 0) {
            ticketId = col.tickets[0].id;
            break;
          }
        }
      }
    } catch (e) {
      console.log('board fallback fetch failed:', String(e));
    }
  }

  if (ticketId == null) {
    console.log('No tickets found to drill into; skipping ticket-detail walk.');
    findings.push({
      route: '/tickets/:id (drill-in, skipped)',
      label: 'tickets-drill-skipped',
      page_errors: [],
      console_messages: [],
      failed_requests: [],
    });
    await ctx.close();
    return;
  }

  console.log(`navigating to /tickets/${ticketId}`);
  await page.goto(`${BASE}/tickets/${ticketId}`, {
    waitUntil: 'networkidle',
    timeout: 15000,
  });
  await page.waitForTimeout(1500);
  await page.screenshot({
    path: path.join(OUT_DIR, 'ticket-detail.png'),
    fullPage: true,
  });

  // Sanity assertions: header should mention the ticket id; Sessions and
  // Comments sections should exist.
  const bodyText = await page.evaluate(() => document.body.innerText);
  const headerHasId = bodyText.includes(`#${ticketId}`);
  const hasSessionsSection = bodyText.includes('Sessions');
  const hasCommentsSection = bodyText.includes('Comments');
  const hasDependenciesSection = bodyText.includes('Dependencies');

  findings.push({
    route: '/tickets/:id (drill-in)',
    label: 'tickets-drill',
    page_errors: errors,
    console_messages: consoleMsgs,
    failed_requests: failedRequests,
    screenshot: path.join(OUT_DIR, 'ticket-detail.png'),
    assertions: {
      ticket_id: ticketId,
      header_contains_id: headerHasId,
      has_sessions_section: hasSessionsSection,
      has_comments_section: hasCommentsSection,
      has_dependencies_section: hasDependenciesSection,
    },
  });
  await ctx.close();
}

async function driveBoardListToggle(browser) {
  console.log('\n=== Board/List toggle walk ===');
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

  await page.goto(`${BASE}/board`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(1500);
  await page.screenshot({
    path: path.join(OUT_DIR, 'board-mode.png'),
    fullPage: true,
  });

  // Click the "List" tab.
  const listBtn = await page.$('button:has-text("List")');
  let listModeBodyText = '';
  if (listBtn) {
    await listBtn.click();
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: path.join(OUT_DIR, 'list-mode.png'),
      fullPage: true,
    });
    listModeBodyText = await page.evaluate(() => document.body.innerText);
  } else {
    console.log('List tab button not found.');
  }

  // Check: sidebar should NOT contain a Workspace switcher (Finding #3).
  // The sidebar's `select#ws-switch` is the legacy id; absence is success.
  const wsSwitcher = await page.$('#ws-switch');
  const sidebarHasWorkspace = wsSwitcher !== null;
  // Per-page workspace dropdown SHOULD exist on the Tickets page.
  const pageHasWorkspaceFilter =
    listModeBodyText.includes('Workspace:') ||
    (await page.$('label:has-text("Workspace")')) !== null;

  findings.push({
    route: '/board (Board/List toggle)',
    label: 'board-list-toggle',
    page_errors: errors,
    console_messages: consoleMsgs,
    failed_requests: failedRequests,
    screenshot: path.join(OUT_DIR, 'list-mode.png'),
    assertions: {
      list_button_clicked: listBtn !== null,
      sidebar_has_legacy_workspace_switcher: sidebarHasWorkspace,
      page_has_workspace_filter: pageHasWorkspaceFilter,
    },
  });
  await ctx.close();
}

async function driveSessionDetail(browser) {
  console.log('\n=== Sessions detail walk ===');
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

  await page.goto(BASE + '/sessions', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(1500);
  // Click the first session row link (an <a> wrapping a <code>).
  const firstLink = await page.$('a[href^="/sessions/"]');
  if (firstLink) {
    await firstLink.click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(OUT_DIR, 'session-detail.png'), fullPage: true });
  } else {
    console.log('No session rows to drill into (empty list).');
  }

  findings.push({
    route: '/sessions/:id (drill-in)',
    label: 'sessions-drill',
    page_errors: errors,
    console_messages: consoleMsgs,
    failed_requests: failedRequests,
    screenshot: path.join(OUT_DIR, 'session-detail.png'),
  });
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  for (const route of PAGES) {
    console.log(`\n=== visiting ${route.path} ===`);
    await visit(browser, route);
  }
  await driveSessionDetail(browser);
  await driveProfileDetail(browser);
  await driveTicketDetail(browser);
  await driveBoardListToggle(browser);
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
