import { test, expect } from '@playwright/test';

test.describe('Messages', () => {
  test('loads messages page with controls', async ({ page }) => {
    await page.goto('/messages');
    await expect(page.locator('h2')).toHaveText('Messages', { timeout: 10_000 });

    // Sender selector
    await expect(page.getByText('Send as:')).toBeVisible();
    // New conversation controls
    await expect(page.getByText('New conversation with:')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start' })).toBeVisible();
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

    // Find thread containing our test agents and click it
    const threadBtn = page.locator('button').filter({ hasText: 'e2e-sender' });
    await expect(threadBtn.first()).toBeVisible({ timeout: 10_000 });
    await threadBtn.first().click();

    // Wait for conversation to load and check the message is visible
    await expect(page.getByText(testMsg, { exact: true })).toBeVisible({ timeout: 5_000 });
  });
});
