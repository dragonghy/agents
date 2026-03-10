import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test('loads and shows agent cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h2')).toHaveText('Dashboard', { timeout: 10_000 });

    // Should have at least one agent card with a link to agent detail
    const agentCards = page.locator('a[href^="/agents/"]');
    await expect(agentCards.first()).toBeVisible();
  });

  test('shows Dispatch All button', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Dispatch All' })).toBeVisible({ timeout: 10_000 });
  });

  test('agent cards show workload stats', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('h2')).toHaveText('Dashboard', { timeout: 10_000 });

    // Each card should have workload indicators
    await expect(page.getByText('active').first()).toBeVisible();
    await expect(page.getByText('new').first()).toBeVisible();
    await expect(page.getByText('blocked').first()).toBeVisible();
  });
});
