import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// maplibre v6 的样式解析跑在独立 worker 里，SDK 以 `new URL('./maplibre-gl-worker.mjs', import.meta.url)`
// 运行时拼路径——打包器无法静态分析，产物里没有该文件，worker 404 后地图静默空白（dev/build 皆然）。
// 对策：把 worker 与其 import 的 shared 运行块按原样输出到 /maplibre/，运行时用 setWorkerUrl 显式指过去
// （见 src/constants/map.ts）。两个文件必须成对且同目录，worker 内是相对 import。
const MAPLIBRE_WORKER_FILES = ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']

function maplibreWorkerAssets(): Plugin {
  const distDir = fileURLToPath(new URL('./node_modules/maplibre-gl/dist', import.meta.url))
  const read = (name: string) => readFileSync(`${distDir}/${name}`, 'utf-8')
  return {
    name: 'maplibre-worker-assets',
    configureServer(server) {
      // 挂在 Vite 内部中间件之前的早跑钩子：/maplibre/* 不与任何内部路由冲突
      server.middlewares.use('/maplibre', (req, res, next) => {
        const name = (req.url ?? '').split('?')[0].replace(/^\//, '')
        if (!MAPLIBRE_WORKER_FILES.includes(name)) return next()
        res.setHeader('Content-Type', 'text/javascript; charset=utf-8')
        res.end(read(name))
      })
    },
    generateBundle() {
      for (const name of MAPLIBRE_WORKER_FILES) {
        this.emitFile({ type: 'asset', fileName: `maplibre/${name}`, source: read(name) })
      }
    },
  }
}

export default defineConfig({
  plugins: [
    vue(),
    maplibreWorkerAssets(),
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
        // 第三方依赖分组（§5.6）：echarts/zrender 独立成块；vue/pinia/axios
        // 等运行时基础库归 vendor（模块粒度独立，无桶 re-export 全量风险）。
        // 注意：element-plus 及其依赖（@vueuse/dayjs/lodash-es 等）必须保持自然分包
        // （按组件粒度自动切 chunk）——实测对 EP 归组会连同 'element-plus/es' 桶
        // re-export 闭包整体保留，导致「形按需实全量」（单 chunk 冲到 ~812KB）。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](echarts|zrender)/.test(id)) return 'echarts'
          // 地图栈独立成块（仅随详情页懒加载；避免与详情 chunk 混成超大单块）
          if (/[\\/]node_modules[\\/]maplibre-gl/.test(id)) return 'map'
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
      // 后端统一到 FastAPI（M7-b 切流量）：业务端点与 agent 面同进程同端口。
      // 双跑期已互认同一 JWT_SECRET 与 TA_AUTH cookie，切换不掉登录态。
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    // 单测只覆盖纯逻辑（store reducer / SSE 帧解析）；happy-dom 提供 window/localStorage。
    // element-plus 必须内联交给 Vite transform：其 ESM 内含 .css 副作用导入，
    // 被 vitest 外部化后 Node 的 ESM loader 会直接抛 "Unknown file extension .css"。
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
    server: {
      deps: {
        inline: ['element-plus'],
      },
    },
  },
})
