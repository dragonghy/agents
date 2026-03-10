import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PORT = 8767;
const agentsMcpDir = path.resolve(__dirname, '..');
const configPath = path.resolve(agentsMcpDir, '..', '..', 'agents.yaml');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 1,
  workers: 1,
  reporter: 'list',
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
  webServer: {
    command: [
      `cd '${agentsMcpDir}'`,
      `&&`,
      `AGENTS_CONFIG_PATH='${configPath}'`,
      `.venv/bin/python -m agents_mcp.server --daemon --port ${PORT} --no-dispatch`,
    ].join(' '),
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 15_000,
  },
});
