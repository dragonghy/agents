/**
 * Capture Web UI screenshots for README.
 * Run: npx playwright test docs/screenshots/capture.mjs --headed
 * Or:  node docs/screenshots/capture.mjs
 */
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BASE_URL = 'http://localhost:8765';
const VIEWPORT = { width: 1440, height: 900 };

const pages = [
  { name: 'dashboard', path: '/', waitFor: 2000 },
  { name: 'agents', path: '/agents', waitFor: 2000 },
  { name: 'token-usage', path: '/tokens', waitFor: 3000 },
  { name: 'tickets', path: '/tickets', waitFor: 2000 },
  { name: 'messages', path: '/messages', waitFor: 2000 },
];

async function capture() {
  const browser = await chromium.launch({ headless: true });

  for (const mode of ['light', 'dark']) {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      colorScheme: mode,
    });
    const page = await context.newPage();

    for (const { name, path, waitFor } of pages) {
      await page.goto(`${BASE_URL}${path}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(waitFor);

      const filename = `${name}-${mode}.png`;
      await page.screenshot({
        path: join(__dirname, filename),
        fullPage: false,
      });
      console.log(`Captured: ${filename}`);
    }

    await context.close();
  }

  await browser.close();
  console.log('\nDone! Screenshots saved to docs/screenshots/');
}

capture().catch(console.error);
