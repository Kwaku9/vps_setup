import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Served by the dashboard at /m/ (see ops_dashboard/api/main.py, MOBILE_DIST).
export default defineConfig({
  base: '/m/',
  plugins: [svelte()],
  build: { target: 'es2022', chunkSizeWarningLimit: 300 },
  server: {
    port: 5181,
    proxy: {
      '/api': { target: 'http://localhost:8090', ws: true },
      '/auth': { target: 'http://localhost:8090' },
    },
  },
});
