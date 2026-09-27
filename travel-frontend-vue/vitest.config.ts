import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// Keep the existing Vue regression suite runnable while the app entry uses React.
// Test transforms do not rewrite the committed component declarations.
export default defineConfig({
  plugins: [
    vue(),
    AutoImport({ imports: [], resolvers: [ElementPlusResolver()], dts: false }),
    Components({ resolvers: [ElementPlusResolver()], dts: false }),
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    server: { deps: { inline: ['element-plus'] } },
  },
})
