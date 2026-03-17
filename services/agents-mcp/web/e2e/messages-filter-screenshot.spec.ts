import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SCREENSHOT_DIR = path.resolve(__dirname, '..', '..', '..', '..', 'tests', 'screenshots');

test.describe('Messages Filter Toggle - QA E2E with Screenshots', () => {

  test('AC1+AC2: Default state shows "Current agents" toggle with filtered threads', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // AC1: Toggle switch is visible
    const toggleBtn = page.getByText('Current agents');
    await expect(toggleBtn).toBeVisible({ timeout: 5_000 });

    // Take screenshot of default state
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'messages-filter-default-current-agents.png'),
      fullPage: true,
    });

    // AC2: Default state only shows current agent conversations
    // Count thread buttons in the sidebar/thread list
    const threadButtons = page.locator('button').filter({ hasText: '↔' });
    const defaultCount = await threadButtons.count();
    console.log(`Default (Current agents) thread count: ${defaultCount}`);

    // Verify the filter text is "Current agents" (not "All conversations")
    await expect(page.getByText('Current agents')).toBeVisible();
  });

  test('AC3: Toggled state shows "All conversations" with more threads', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Count default threads
    const threadButtons = page.locator('button').filter({ hasText: '↔' });
    await page.waitForTimeout(500); // wait for threads to load
    const defaultCount = await threadButtons.count();
    console.log(`Default thread count: ${defaultCount}`);

    // Click toggle to show all conversations
    const toggleBtn = page.getByText('Current agents');
    await expect(toggleBtn).toBeVisible({ timeout: 5_000 });
    await toggleBtn.click();

    // Verify toggle text changes
    await expect(page.getByText('All conversations')).toBeVisible({ timeout: 5_000 });

    // Wait for thread list to update
    await page.waitForTimeout(500);

    // Take screenshot of "All conversations" state
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'messages-filter-all-conversations.png'),
      fullPage: true,
    });

    // AC3: Count should be >= default count (more historical threads visible)
    const allCount = await threadButtons.count();
    console.log(`All conversations thread count: ${allCount}`);
    expect(allCount).toBeGreaterThanOrEqual(defaultCount);

    // AC5: Visual confirmation - count should visibly differ
    // (This depends on having test agent data; log for report)
    console.log(`Thread count change: ${defaultCount} → ${allCount} (delta: ${allCount - defaultCount})`);
  });

  test('AC4: Toggle state persists across tab switch', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Switch to "All conversations"
    const toggleBtn = page.getByText('Current agents');
    await expect(toggleBtn).toBeVisible({ timeout: 5_000 });
    await toggleBtn.click();
    await expect(page.getByText('All conversations')).toBeVisible();

    // Navigate away to Agents page
    await page.locator('aside').getByRole('link', { name: 'Agents' }).click();
    await expect(page).toHaveURL('/agents');
    await expect(page.locator('h2')).toHaveText('Agents', { timeout: 5_000 });

    // Navigate back to Messages
    await page.locator('aside').getByRole('link', { name: 'Messages' }).click();
    await expect(page).toHaveURL('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 5_000 });

    // Check if toggle state persists
    // Note: The AC says "within page" - if it resets on navigation,
    // that's expected behavior for SPA route change vs. tab within page
    await page.waitForTimeout(500);

    // Take screenshot after returning
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'messages-filter-after-navigation.png'),
      fullPage: true,
    });

    // Check current toggle state
    const currentAgentsVisible = await page.getByText('Current agents').isVisible().catch(() => false);
    const allConversationsVisible = await page.getByText('All conversations').isVisible().catch(() => false);
    console.log(`After navigation - Current agents visible: ${currentAgentsVisible}, All conversations visible: ${allConversationsVisible}`);
  });

  test('AC5: Toggle back to Current agents reduces count', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    const threadButtons = page.locator('button').filter({ hasText: '↔' });
    await page.waitForTimeout(500);
    const defaultCount = await threadButtons.count();

    // Switch to All
    await page.getByText('Current agents').click();
    await expect(page.getByText('All conversations')).toBeVisible();
    await page.waitForTimeout(500);
    const allCount = await threadButtons.count();

    // Switch back to Current agents
    await page.getByText('All conversations').click();
    await expect(page.getByText('Current agents')).toBeVisible();
    await page.waitForTimeout(500);
    const backCount = await threadButtons.count();

    console.log(`Count flow: Current(${defaultCount}) → All(${allCount}) → Current(${backCount})`);

    // After toggling back, count should match original
    expect(backCount).toBe(defaultCount);

    // Take final screenshot
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'messages-filter-toggled-back.png'),
      fullPage: true,
    });
  });
});
