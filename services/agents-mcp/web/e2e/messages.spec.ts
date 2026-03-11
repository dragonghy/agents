import { test, expect } from '@playwright/test';

test.describe('Messages', () => {
  test('loads messages page with controls and filter toggle', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Sender selector
    await expect(page.getByText('Send as:')).toBeVisible();
    // New conversation controls
    await expect(page.getByText('New conversation with:')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start' })).toBeVisible();
    // Filter toggle - defaults to "Current agents"
    await expect(page.getByText('Current agents')).toBeVisible();
  });

  test('filter toggle switches between current agents and all', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Default: "Current agents"
    const toggleBtn = page.getByText('Current agents');
    await expect(toggleBtn).toBeVisible();

    // Click to switch to "All conversations"
    await toggleBtn.click();
    await expect(page.getByText('All conversations')).toBeVisible();

    // Click again to switch back
    await page.getByText('All conversations').click();
    await expect(page.getByText('Current agents')).toBeVisible();
  });

  test('shows thread list or empty state', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Should show either threads or empty state or prompt to select
    const pageText = await page.textContent('body');
    const hasContent = pageText!.includes('No conversations yet')
      || pageText!.includes('No messages in this conversation')
      || pageText!.includes('Select a conversation')
      || pageText!.includes('\u2194');  // harr character in threads
    expect(hasContent).toBeTruthy();
  });

  test('send message via API and verify it appears', async ({ page, request }) => {
    const ts = Date.now();
    const testMsg = `e2e-test-${ts}`;

    // Send a test message via API
    const sendRes = await request.post('/api/v1/messages/send', {
      data: {
        from_agent: 'e2e-sender',
        to_agent: 'e2e-receiver',
        message: testMsg,
      },
    });
    expect(sendRes.ok()).toBeTruthy();

    // Navigate to messages page
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Switch to "All conversations" to see test agent messages
    const toggleBtn = page.getByText('Current agents');
    await expect(toggleBtn).toBeVisible({ timeout: 5_000 });
    await toggleBtn.click();
    await expect(page.getByText('All conversations')).toBeVisible();

    // Find thread containing our test agents and click it
    const threadBtn = page.locator('button').filter({ hasText: 'e2e-sender' });
    await expect(threadBtn.first()).toBeVisible({ timeout: 10_000 });
    await threadBtn.first().click();

    // Wait for conversation to load and check the message is visible
    await expect(page.getByText(testMsg, { exact: true })).toBeVisible({ timeout: 5_000 });
  });
});
