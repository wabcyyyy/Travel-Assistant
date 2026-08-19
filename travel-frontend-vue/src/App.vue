<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="logo" @click="$router.push('/')">旅行助手 Travel Assistant</div>
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
      <el-button v-else type="primary" @click="$router.push('/login')">登录</el-button>
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
  border-bottom: 1px solid var(--el-border-color-light);
}

.logo {
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.menu {
  flex: 1;
}

.user-name {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>