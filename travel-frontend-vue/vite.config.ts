import { defineConfig } from 'vite'

export default defineConfig({
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
