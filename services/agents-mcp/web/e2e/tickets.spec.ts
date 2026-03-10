import { test, expect } from '@playwright/test';

test.describe('Tickets List', () => {
  test('loads ticket table', async ({ page }) => {
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    // Should have a table with headers
    await expect(page.getByRole('columnheader', { name: 'ID' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Title' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Assignee' })).toBeVisible();
  });

  test('has New Ticket button and status filter', async ({ page }) => {
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    await expect(page.getByRole('button', { name: 'New Ticket' })).toBeVisible();
    // Status filter dropdown
    await expect(page.locator('select').first()).toBeVisible();
  });

  test('opens New Ticket modal', async ({ page }) => {
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    await page.getByRole('button', { name: 'New Ticket' }).click();

    // Modal should appear
    await expect(page.getByText('Create Ticket')).toBeVisible();
    await expect(page.getByPlaceholder('Ticket headline')).toBeVisible();

    // Cancel closes modal
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByText('Create Ticket')).toBeHidden();
  });

  test('navigates to ticket detail', async ({ page }) => {
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    // Wait for ticket rows to appear, then click the first one
    const ticketLinks = page.locator('td a[href^="/tickets/"]');
    await expect(ticketLinks.first()).toBeVisible({ timeout: 10_000 });
    await ticketLinks.first().click();
    // Should navigate to ticket detail - check for "Back to Tickets" link
    await expect(page.getByText('Back to Tickets')).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('Ticket Detail', () => {
  test('shows ticket info and comment section', async ({ page }) => {
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    const ticketLinks = page.locator('td a[href^="/tickets/"]');
    await expect(ticketLinks.first()).toBeVisible({ timeout: 10_000 });

    await ticketLinks.first().click();
    // Wait for ticket detail to finish loading
    await expect(page.getByText('Back to Tickets')).toBeVisible({ timeout: 10_000 });

    // Should show ticket headline with #ID prefix
    await expect(page.locator('h2').first()).toContainText('#');

    // Comments section heading (e.g. "Comments (0)" or "Comments (3)")
    await expect(page.locator('h3').filter({ hasText: 'Comments' })).toBeVisible();
    // Comment input
    await expect(page.getByPlaceholder(/comment/i)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add Comment' })).toBeVisible();

    // Sidebar labels (uppercase labels)
    await expect(page.locator('label').filter({ hasText: 'Status' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'Assignee' })).toBeVisible();
    await expect(page.locator('label').filter({ hasText: 'Priority' })).toBeVisible();
  });

  test('has Reassign button in sidebar', async ({ page }) => {
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    const ticketLinks = page.locator('td a[href^="/tickets/"]');
    await expect(ticketLinks.first()).toBeVisible({ timeout: 10_000 });

    await ticketLinks.first().click();
    await expect(page.getByText('Back to Tickets')).toBeVisible({ timeout: 10_000 });

    // Reassign button
    const reassignBtn = page.getByRole('button', { name: 'Reassign' });
    await expect(reassignBtn).toBeVisible();

    // Click Reassign to expand the panel
    await reassignBtn.click();
    await expect(page.getByPlaceholder('Handoff note')).toBeVisible();
    // Verify the reassign select dropdown is visible (the option text is inside a select)
    const reassignSelect = page.locator('select').filter({ hasText: 'Select agent...' });
    await expect(reassignSelect).toBeVisible();
  });

  test('SPA fallback: direct URL loads ticket detail', async ({ page }) => {
    // First get a valid ticket ID from the list
    await page.goto('/tickets');
    await expect(page.locator('h2')).toHaveText('Tickets', { timeout: 10_000 });

    const ticketLinks = page.locator('td a[href^="/tickets/"]');
    await expect(ticketLinks.first()).toBeVisible({ timeout: 10_000 });

    const href = await ticketLinks.first().getAttribute('href');
    // Navigate directly to the ticket URL
    await page.goto(href!);
    await expect(page.getByText('Back to Tickets')).toBeVisible({ timeout: 10_000 });
  });
});
