<template>
  <el-container class="layout">
    <el-header class="header lp-header" height="60px">
      <div class="logo lp-logo" @click="$router.push('/')">
        <span class="mark"></span>
        <span class="zh">旅行助手</span>
        <span class="en">Travel Assistant</span>
      </div>
      <el-menu
        mode="horizontal"
        :ellipsis="false"
        :router="true"
        :default-active="$route.path"
        class="menu"
      >
        <el-menu-item index="/">首页</el-menu-item>
        <el-menu-item index="/generate">行程生成</el-menu-item>
        <el-menu-item index="/trips">我的行程</el-menu-item>
      </el-menu>
      <div v-if="userStore.token" class="user-area">
        <el-dropdown @command="onCommand">
          <span class="user-name">
            {{ userStore.username }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <el-button v-else type="primary" plain @click="$router.push('/login')">登录</el-button>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ArrowDown } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { useUserStore } from './store/user'

const router = useRouter()
const userStore = useUserStore()

function onCommand(command: string) {
  if (command === 'logout') {
    userStore.logout()
    router.push({ name: 'login' })
  }
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
}

.header {
  display: flex;
  align-items: center;
  gap: 24px;
}

.menu {
  flex: 1;
  border-bottom: none !important;
  background: transparent;
}

.menu :deep(.el-menu-item) {
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--lp-ink-soft);
  border-bottom: 2px solid transparent;
}

.menu :deep(.el-menu-item.is-active) {
  color: var(--lp-ink);
  border-bottom-color: var(--lp-accent);
}

.menu :deep(.el-menu-item:hover) {
  background: var(--lp-sand);
  color: var(--lp-ink);
}

.user-name {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: var(--lp-ink);
}
</style>