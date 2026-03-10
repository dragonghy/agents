import { test, expect } from '@playwright/test';

test.describe('WebSocket', () => {
  test('connects to WebSocket endpoint', async ({ page }) => {
    // Navigate to dashboard (which uses useWebSocket implicitly via future integration)
    await page.goto('/');
    await expect(page.locator('h2')).toHaveText('Dashboard', { timeout: 10_000 });

    // Test WebSocket connectivity directly via page.evaluate
    const wsConnected = await page.evaluate(async () => {
      return new Promise<boolean>((resolve) => {
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        const timer = setTimeout(() => {
          ws.close();
          resolve(false);
        }, 5000);
        ws.onopen = () => {
          clearTimeout(timer);
          ws.close();
          resolve(true);
        };
        ws.onerror = () => {
          clearTimeout(timer);
          resolve(false);
        };
      });
    });

    expect(wsConnected).toBe(true);
  });

  test('receives broadcast messages', async ({ page, request }) => {
    await page.goto('/');
    await expect(page.locator('h2')).toHaveText('Dashboard', { timeout: 10_000 });

    // Open a WS connection and listen for events
    const receivedEvent = await page.evaluate(async () => {
      return new Promise<boolean>((resolve) => {
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        const timer = setTimeout(() => {
          ws.close();
          resolve(false);
        }, 8000);
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'message_sent') {
              clearTimeout(timer);
              ws.close();
              resolve(true);
            }
          } catch {
            // ignore parse errors
          }
        };
        ws.onopen = () => {
          // Once connected, send a message via API to trigger a broadcast
          fetch('/api/v1/messages/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              from_agent: 'ws-test-sender',
              to_agent: 'ws-test-receiver',
              message: `ws-test-${Date.now()}`,
            }),
          });
        };
      });
    });

    expect(receivedEvent).toBe(true);
  });
});
