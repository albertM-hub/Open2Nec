import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// En développement, /api est redirigé vers FastAPI (uvicorn sur le port 8000)
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
