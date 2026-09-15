<template>
  <!-- EP 按需后经 ConfigProvider 全局下发中文 locale（替代原 app.use(ElementPlus, { locale })） -->
  <el-config-provider :locale="zhCn">
    <!-- 公开页（分享）不渲染 AppShell：ShareView 自带轻顶栏（SPEC §1.3） -->
    <router-view v-if="isPublic" />
    <AppShell v-else><router-view /></AppShell>
    <!-- 自研全局提示宿主（v2.6 §19.2）：任何模块经 ui/toast 触发 -->
    <AppToastHost />
    <!-- 自研确认对话框宿主（v2.6 §19.2）：任何模块经 ui/confirm 触发 -->
    <AppConfirmHost />
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import AppShell from './components/layout/AppShell.vue'
import AppConfirmHost from './components/ui/AppConfirmHost.vue'
import AppToastHost from './components/ui/AppToastHost.vue'

const route = useRoute()
const isPublic = computed(() => route.meta.public === true)
</script>
