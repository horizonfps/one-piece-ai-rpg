import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Dev: Vite serve em :5173 e faz proxy de /api pro FastAPI (:8400) — sem CORS no caminho feliz.
// Build: gera dist/ que o FastAPI serve em produção (web-local).
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8400',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
