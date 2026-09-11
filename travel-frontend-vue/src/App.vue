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
        class="menu desktop-menu"
      >
        <el-menu-item index="/">首页</el-menu-item>
        <el-menu-item index="/generate">行程生成</el-menu-item>
        <el-menu-item index="/trips">我的行程</el-menu-item>
        <el-menu-item v-if="userStore.role === 'admin'" index="/admin">后台管理</el-menu-item>
      </el-menu>
      <div class="header-end">
        <div v-if="userStore.username" class="user-area desktop-only">
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
        <el-button v-else type="primary" class="desktop-only" @click="$router.push('/login')">
          登录
        </el-button>
        <button
          type="button"
          class="nav-toggle"
          :aria-expanded="mobileNavOpen ? 'true' : 'false'"
          aria-label="打开导航菜单"
          @click="mobileNavOpen = true"
        >
          <span></span><span></span><span></span>
        </button>
      </div>
    </el-header>

    <el-drawer
      v-model="mobileNavOpen"
      direction="rtl"
      size="min(280px, 86vw)"
      :with-header="false"
      append-to-body
      class="mobile-nav-drawer"
    >
      <nav class="mobile-nav">
        <button
          v-for="item in navItems"
          :key="item.path"
          type="button"
          class="mobile-nav-item"
          :class="{ active: $route.path === item.path }"
          @click="goPath(item.path)"
        >
          {{ item.label }}
        </button>
        <hr class="lp-rule" />
        <button
          v-if="userStore.username"
          type="button"
          class="mobile-nav-item"
          @click="onCommand('logout')"
        >
          退出登录
        </button>
        <button
          v-else
          type="button"
          class="mobile-nav-item"
          @click="goPath('/login')"
        >
          登录
        </button>
      </nav>
    </el-drawer>

    <el-main>
      <div class="main-container">
        <router-view />
      </div>
      <footer class="lp-footer">
        <p>
          本地演示项目 · 数据来自高德 / Wikivoyage(CC BY-SA) / Unsplash 等，仅供学习展示 ·
          行程中的「待确认」项请出发前自行核实
        </p>
      </footer>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { useUserStore } from './store/user'
import { logoutApi } from './api'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const mobileNavOpen = ref(false)

const navItems = computed(() => {
  const items = [
    { path: '/', label: '首页' },
    { path: '/generate', label: '行程生成' },
    { path: '/trips', label: '我的行程' },
  ]
  if (userStore.role === 'admin') {
    items.push({ path: '/admin', label: '后台管理' })
  }
  return items
})

watch(
  () => route.path,
  () => {
    mobileNavOpen.value = false
  },
)

function goPath(path: string) {
  mobileNavOpen.value = false
  void router.push(path)
}

async function onCommand(command: string) {
  if (command === 'logout') {
    try {
      await logoutApi()
    } catch {
      /* 吊销失败仍清本地态，避免卡在已失效会话 */
    }
    userStore.logout()
    router.push({ name: 'login' })
  }
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
}

/* 全局内容宽度：宽屏下居中，避免超宽拉伸 */
.main-container {
  max-width: var(--lp-content-wide, 1280px);
  margin: 0 auto;
}

.header {
  position: sticky;
  top: 0;
  z-index: 100;
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
  background: transparent;
  border-bottom: 2px solid transparent;
  transition:
    color 0.15s ease,
    border-color 0.15s ease;
}

.menu :deep(.el-menu-item.is-active) {
  color: var(--lp-accent);
  background: transparent;
  border-bottom-color: var(--lp-accent);
}

.menu :deep(.el-menu-item:hover) {
  background: var(--lp-sand);
  color: var(--lp-ink);
}

.header-end {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.user-name {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: var(--lp-ink);
  padding: 6px 10px;
  border-radius: 8px;
  transition: background 0.15s ease;
}

.user-name:hover {
  background: var(--lp-sand);
}

.nav-toggle {
  display: none;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  width: 44px;
  height: 44px;
  padding: 10px;
  border: 1px solid var(--lp-border);
  border-radius: 10px;
  background: var(--lp-surface);
  cursor: pointer;
}

.nav-toggle span {
  display: block;
  height: 2px;
  border-radius: 1px;
  background: var(--lp-ink);
}

.mobile-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 4px;
}

.mobile-nav-item {
  display: block;
  width: 100%;
  min-height: 44px;
  padding: 10px 14px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--lp-ink-soft);
  font-size: 15px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.mobile-nav-item:hover,
.mobile-nav-item.active {
  background: var(--lp-sand);
  color: var(--lp-accent);
}

.mobile-nav .lp-rule {
  margin: 8px 10px;
}

@media (max-width: 860px) {
  .desktop-menu,
  .desktop-only {
    display: none !important;
  }

  .nav-toggle {
    display: flex;
  }

  .header {
    gap: 12px;
  }

  .lp-logo .en {
    display: none;
  }
}

.lp-footer {
  margin-top: 24px;
  padding: 16px 8px 8px;
  border-top: 1px solid var(--lp-border, #e8e4dc);
  text-align: center;
  color: #8a857c;
  font-size: 12px;
  line-height: 1.6;
}

.lp-footer p {
  margin: 0;
}
</style>
