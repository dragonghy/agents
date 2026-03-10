import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('sidebar contains all navigation links', async ({ page }) => {
    await page.goto('/');

    const sidebar = page.locator('aside');
    await expect(sidebar.getByText('Agent Hub')).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Dashboard' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Agents' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Tickets' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Messages' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Feedback' })).toBeVisible();
  });

  test('sidebar navigation works for all routes', async ({ page }) => {
    await page.goto('/');

    // Navigate to Agents
    await page.locator('aside').getByRole('link', { name: 'Agents' }).click();
    await expect(page).toHaveURL('/agents');
    await expect(page.locator('h2')).toHaveText('Agents');

    // Navigate to Tickets
    await page.locator('aside').getByRole('link', { name: 'Tickets' }).click();
    await expect(page).toHaveURL('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets');

    // Navigate to Messages
    await page.locator('aside').getByRole('link', { name: 'Messages' }).click();
    await expect(page).toHaveURL('/messages');
    await expect(page.locator('h2')).toHaveText('Messages');

    // Navigate to Feedback
    await page.locator('aside').getByRole('link', { name: 'Feedback' }).click();
    await expect(page).toHaveURL('/feedback');
    await expect(page.locator('h2')).toHaveText('Submit Feedback');

    // Navigate back to Dashboard
    await page.locator('aside').getByRole('link', { name: 'Dashboard' }).click();
    await expect(page).toHaveURL('/');
    await expect(page.locator('h2')).toHaveText('Dashboard');
  });

  test('health endpoint returns ok', async ({ request }) => {
    const res = await request.get('/api/v1/health');
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data.status).toBe('ok');
  });
});
