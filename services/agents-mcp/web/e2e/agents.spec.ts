import { test, expect } from '@playwright/test';

test.describe('Agents List', () => {
  test('loads agent table', async ({ page }) => {
    await page.goto('/agents');
    await expect(page.locator('h2')).toHaveText('Agents', { timeout: 10_000 });

    // Should have a table with headers
    await expect(page.getByRole('columnheader', { name: 'Agent' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Role' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();

    // Should have at least one agent row with a link
    const agentLinks = page.locator('td a[href^="/agents/"]');
    await expect(agentLinks.first()).toBeVisible();
  });

  test('navigates to agent detail via click', async ({ page }) => {
    await page.goto('/agents');
    await expect(page.locator('h2')).toHaveText('Agents', { timeout: 10_000 });

    // Click first agent link
    const firstAgent = page.locator('td a[href^="/agents/"]').first();
    const agentId = await firstAgent.textContent();
    await firstAgent.click();

    // Should navigate to agent detail
    await expect(page).toHaveURL(new RegExp(`/agents/${agentId}`));
    await expect(page.locator('h2')).toContainText(agentId!);
  });
});

test.describe('Agent Detail', () => {
  test('shows profile, workload, and terminal sections', async ({ page }) => {
    // Navigate to agents list first, then click into a detail
    await page.goto('/agents');
    await expect(page.locator('h2')).toHaveText('Agents', { timeout: 10_000 });

    const firstAgent = page.locator('td a[href^="/agents/"]').first();
    await firstAgent.click();

    // Wait for agent detail to finish loading (Profile heading only appears after load)
    await expect(page.getByRole('heading', { name: 'Profile' })).toBeVisible({ timeout: 10_000 });
    // Workload section heading
    await expect(page.getByRole('heading', { name: 'Workload' })).toBeVisible();
    // Terminal section heading
    await expect(page.getByRole('heading', { name: 'Terminal' })).toBeVisible();
    // Back link
    await expect(page.getByText('Back to Agents')).toBeVisible();
  });

  test('has Dispatch button', async ({ page }) => {
    await page.goto('/agents');
    await expect(page.locator('h2')).toHaveText('Agents', { timeout: 10_000 });

    const firstAgent = page.locator('td a[href^="/agents/"]').first();
    await firstAgent.click();

    await expect(page.getByRole('heading', { name: 'Profile' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: 'Dispatch' })).toBeVisible();
  });

  test('SPA fallback: direct URL loads agent detail', async ({ page }) => {
    // Navigate to agents list to get a valid agent ID
    await page.goto('/agents');
    await expect(page.locator('h2')).toHaveText('Agents', { timeout: 10_000 });

    const firstAgent = page.locator('td a[href^="/agents/"]').first();
    const agentId = await firstAgent.textContent();

    // Navigate directly to the agent detail URL
    await page.goto(`/agents/${agentId}`);
    // SPA fallback should serve index.html and React Router handles the route
    await expect(page.locator('h2')).toContainText(agentId!, { timeout: 10_000 });
  });
});
