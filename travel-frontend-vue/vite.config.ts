import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需：模板组件 + 函数式 API（ElMessage 等）均走 resolver，
    // 样式同步按需注入（importStyle 默认 'css'），避免「形按需实全量」。
    AutoImport({
      imports: [],
      resolvers: [ElementPlusResolver()],
      // d.ts 生成进 src，纳入 tsconfig include，保证 vue-tsc 严格模式通过
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 第三方依赖分组（§5.6）：echarts/zrender、高德 loader 各自成块；vue/pinia/axios
        // 等运行时基础库归 vendor（模块粒度独立，无桶 re-export 全量风险）。
        // 注意：element-plus 及其依赖（@vueuse/dayjs/lodash-es 等）必须保持自然分包
        // （按组件粒度自动切 chunk）——实测对 EP 归组会连同 'element-plus/es' 桶
        // re-export 闭包整体保留，导致「形按需实全量」（单 chunk 冲到 ~812KB）。
        // Leaflet 走 CDN 动态注入（utils/leaflet.ts），不在 npm 依赖内，无需分组。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](echarts|zrender)/.test(id)) return 'echarts'
          if (/[\\/]node_modules[\\/]@amap[\\/]/.test(id)) return 'maps'
          if (/[\\/]node_modules[\\/](@vue|vue|vue-router|pinia|vue-demi|axios)[\\/]/.test(id)) {
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
