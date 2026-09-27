import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

// React 壳单测配置。Vue 树退役后不再需要 vue 插件与 EP 解析器；
// happy-dom 供涉及 sessionStorage 的用例使用。
export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
  },
})
