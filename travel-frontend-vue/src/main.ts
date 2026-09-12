import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElLoading } from 'element-plus'
// v-loading 指令不经 unplugin resolver（指令不归 Components 插件管），按需手动注册；
// 函数式组件（ElMessage/ElMessageBox）样式由 AutoImport resolver 注入，勿在此全量引样式。
import 'element-plus/es/components/loading/style/css'
import './styles/theme.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 仅注册 loading 指令；其余组件/样式全部按需（见 vite.config.ts 的 resolver）
app.use(ElLoading)

app.mount('#app')
