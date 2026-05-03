import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3001,
    host: '127.0.0.1',
    proxy: {
      // Orchestration v1 API (test harness — Task #17) lives on the daemon
      // at :8765, NOT on the apps/console/backend. Order matters: more
      // specific paths must come BEFORE the catch-all '/api'.
      '/api/v1/orchestration': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
      },
      '/api': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: false,
      },
    },
  },
  build: {
    sourcemap: false,
  },
});
