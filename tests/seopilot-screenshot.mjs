#!/usr/bin/env node
// SEOPilot M1 QA Screenshot Script
// Takes screenshots of key pages for QA verification

import puppeteer from 'puppeteer';
import { mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const screenshotDir = join(__dirname, 'screenshots');
mkdirSync(screenshotDir, { recursive: true });

const BASE_URL = process.env.BASE_URL || 'http://localhost:3456';

async function main() {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });

  // 1. Login page
  console.log('Taking screenshot: /auth/login');
  await page.goto(`${BASE_URL}/auth/login`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await new Promise(r => setTimeout(r, 2000)); // Wait for CSS to load
  await page.screenshot({
    path: join(screenshotDir, 'seopilot-login.png'),
    fullPage: true,
  });
  console.log('  -> saved seopilot-login.png');

  // 2. Root page
  console.log('Taking screenshot: / (root)');
  await page.goto(`${BASE_URL}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({
    path: join(screenshotDir, 'seopilot-root.png'),
    fullPage: true,
  });
  console.log('  -> saved seopilot-root.png');

  // 3. /app route (should show 410 or error without Shopify session)
  console.log('Taking screenshot: /app (expected 410)');
  const response = await page.goto(`${BASE_URL}/app`, { waitUntil: 'domcontentloaded', timeout: 15000 });
  console.log(`  -> HTTP status: ${response.status()}`);
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({
    path: join(screenshotDir, 'seopilot-app-no-session.png'),
    fullPage: true,
  });
  console.log('  -> saved seopilot-app-no-session.png');

  await browser.close();
  console.log('\nAll screenshots saved to:', screenshotDir);
}

main().catch(err => {
  console.error('Screenshot error:', err);
  process.exit(1);
});
