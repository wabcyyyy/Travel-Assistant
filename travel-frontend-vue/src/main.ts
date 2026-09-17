import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElLoading } from 'element-plus'
// v-loading 指令不经 unplugin resolver（指令不归 Components 插件管），按需手动注册；
// 函数式组件（ElMessage/ElMessageBox）样式由 AutoImport resolver 注入，勿在此全量引样式。
// EP 暗色变量（html.dark 生效）：刻意**先于** theme.css 引入——同名选择器下我们的
// --el-* 映射在后、按 CSS 顺序胜出，暗色里主色仍归 --lp-accent 家族。
import 'element-plus/theme-chalk/dark/css-vars.css'
import 'element-plus/es/components/loading/style/css'
import './styles/theme.css'

import App from './App.vue'
import router from './router'
import { applyAppearance } from './styles/appearance'

// 外观契约的唯一运行时入口（SPEC §7.1.4）：首帧引导脚本已在 index.html 先跑一次
applyAppearance(document.documentElement)

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 仅注册 loading 指令；其余组件/样式全部按需（见 vite.config.ts 的 resolver）
app.use(ElLoading)

app.mount('#app')

// PWA（C2.5）：SW 只管应用壳 precache + 离线导航回退；私有数据快照在
// utils/offlineSnapshots（按账号 IndexedDB），与 SW 缓存职责互不重叠。
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  import('virtual:pwa-register').then(({ registerSW }) => registerSW({ immediate: true })).catch(() => {
    /* SW 注册失败不影响线上功能 */
  })
}
