#!/usr/bin/env node
// SEOPilot M1 QA Screenshot Script (Playwright)
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const screenshotDir = join(__dirname, 'screenshots');
mkdirSync(screenshotDir, { recursive: true });

const BASE_URL = process.env.BASE_URL || 'http://localhost:3456';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  // 1. Login page
  console.log('1. Taking screenshot: /auth/login');
  await page.goto(`${BASE_URL}/auth/login`, { timeout: 15000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: join(screenshotDir, 'seopilot-login.png'), fullPage: true });
  console.log('   -> saved seopilot-login.png');

  // Check page content
  const title = await page.textContent('h2');
  console.log(`   -> Page heading: "${title}"`);

  // 2. /app route (expected 410 without session)
  console.log('2. Testing /app route (expected 410)');
  const resp = await page.goto(`${BASE_URL}/app`, { timeout: 15000 });
  console.log(`   -> HTTP status: ${resp.status()}`);
  await page.screenshot({ path: join(screenshotDir, 'seopilot-app-410.png'), fullPage: true });
  console.log('   -> saved seopilot-app-410.png');

  await browser.close();
  console.log('\nDone! Screenshots saved to:', screenshotDir);
}

main().catch(err => { console.error(err); process.exit(1); });
