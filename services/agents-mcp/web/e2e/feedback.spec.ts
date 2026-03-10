import { test, expect } from '@playwright/test';

test.describe('Feedback', () => {
  test('loads feedback form', async ({ page }) => {
    await page.goto('/feedback');
    await expect(page.locator('h2')).toHaveText('Submit Feedback');

    // Form fields - use placeholder text since getByLabel may not match "*"
    await expect(page.getByPlaceholder('Brief description of the feedback')).toBeVisible();
    await expect(page.getByPlaceholder('Detailed feedback')).toBeVisible();

    // Submit button
    await expect(page.getByRole('button', { name: 'Submit Feedback' })).toBeVisible();
  });

  test('submit button disabled when title empty', async ({ page }) => {
    await page.goto('/feedback');

    const submitBtn = page.getByRole('button', { name: 'Submit Feedback' });
    await expect(submitBtn).toBeDisabled();
  });

  test('submit button enabled when title filled', async ({ page }) => {
    await page.goto('/feedback');

    await page.getByPlaceholder('Brief description of the feedback').fill('Test feedback');
    const submitBtn = page.getByRole('button', { name: 'Submit Feedback' });
    await expect(submitBtn).toBeEnabled();
  });

  test('submits feedback and shows success', async ({ page }) => {
    await page.goto('/feedback');

    const ts = Date.now();
    await page.getByPlaceholder('Brief description of the feedback').fill(`E2E Test Feedback ${ts}`);
    await page.getByPlaceholder('Detailed feedback').fill('Automated test feedback');

    await page.getByRole('button', { name: 'Submit Feedback' }).click();

    // Should show success message
    await expect(page.getByText('Feedback submitted successfully')).toBeVisible({ timeout: 10_000 });
    // Should have link to created ticket
    await expect(page.locator('a[href^="/tickets/"]')).toBeVisible();
  });
});
