<template>
  <div class="shell">
    <!-- 同一组件树：≥768px 是左侧常驻 NavRail，<768px 折为底部 BottomBar（CSS 切布局，不做第二套 shell） -->
    <nav class="nav" aria-label="主导航">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
      >
        <el-icon :size="22"><component :is="item.icon" /></el-icon>
        <span class="nav-label">{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="shell-main">
      <header class="topbar lp-header">
        <div class="crumbs" aria-label="面包屑">
          <span class="crumb-brand">旅行助手</span>
          <template v-if="currentTitle">
            <span class="crumb-sep" aria-hidden="true">/</span>
            <span class="crumb-current">{{ currentTitle }}</span>
          </template>
        </div>

        <form class="global-search" role="search" @submit.prevent="submitSearch">
          <el-input
            v-model="keyword"
            placeholder="搜索行程…（回车）"
            clearable
            :prefix-icon="Search"
            aria-label="搜索行程"
          />
        </form>

        <div class="topbar-end">
          <AppearancePopover />
          <template v-if="userStore.username">
            <span class="user-name">{{ userStore.username }}</span>
            <!-- 登出常驻可见（硬约束）：幽灵钮（无描边），不藏进下拉菜单 -->
            <button type="button" class="logout-btn" @click="onLogout">退出</button>
          </template>
          <el-button v-else size="small" type="primary" @click="router.push('/login')">登录</el-button>
        </div>
      </header>

      <main class="content" :class="{ 'is-immersive': route.meta.immersive === true }">
        <div class="content-inner" :class="{ 'is-wide': route.meta.wide === true }"><slot /></div>
      </main>

      <!-- immersive 路由（详情工作台，v2.7 §20 R1）：整页不滚，页脚让位给视口固定布局 -->
      <footer v-if="route.meta.immersive !== true" class="footer">
        <p>
          本地演示项目，仅供学习展示。点位数据来自本地点位知识库（Wikivoyage CC BY-SA 等来源已在数据管线标注），
          图片来自 Wikimedia / Unsplash 等图库并经服务端同源代理。价格与营业时间请以现场或官方渠道为准。
        </p>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Compass, HomeFilled, MagicStick, MapLocation, Search, Setting } from '@element-plus/icons-vue'

import { logoutApi } from '../../api'
import { useUserStore } from '../../store/user'
import AppearancePopover from './AppearancePopover.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const keyword = ref('')

interface NavItem {
  path: string
  label: string
  icon: unknown
}

const navItems = computed<NavItem[]>(() => {
  const items: NavItem[] = [
    { path: '/', label: '今日', icon: HomeFilled },
    { path: '/trips', label: '旅程', icon: Compass },
    { path: '/atlas', label: '图鉴', icon: MapLocation },
    { path: '/generate', label: '生成', icon: MagicStick },
  ]
  // 沿用现状判定源（store/user.ts 读同一 localStorage role）
  if (userStore.role === 'admin') {
    items.push({ path: '/admin', label: '管理端', icon: Setting })
  }
  return items
})

const ROUTE_TITLES: Record<string, string> = {
  home: '今日',
  trips: '旅程',
  atlas: '图鉴',
  'trip-detail': '行程详情',
  generate: '生成',
  login: '登录',
  admin: '管理端',
  'admin-dashboard': '管理端',
  'admin-users': '用户管理',
  'admin-itineraries': '行程管理',
  'admin-tokens': '令牌',
  'admin-agent': 'Agent 监控',
}

const currentTitle = computed(() => ROUTE_TITLES[String(route.name ?? '')] ?? '')

function isActive(path: string): boolean {
  return path === '/' ? route.path === '/' : route.path.startsWith(path)
}

function submitSearch(): void {
  const query = keyword.value.trim()
  router.push({ name: 'trips', query: query ? { q: query } : {} })
}

async function onLogout(): Promise<void> {
  try {
    await logoutApi()
  } catch {
    /* 吊销失败仍清本地态，避免卡在已失效会话 */
  }
  userStore.logout()
  router.push({ name: 'login' })
}
</script>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  min-height: 100vh;
}

/* ---------- 导航（桌面 = 左栏；移动 = 底栏，见媒体查询） ---------- */
.nav {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--lp-space-4) var(--lp-space-2);
  /* 容器用「浅面」而不是描边分层（TREK 的做法）：选中项才是浮起的白胶囊 */
  background: var(--lp-surface-2);
}

.nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--lp-space-2) 4px;
  border-radius: var(--lp-radius-sm);
  color: var(--lp-text-muted);
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.nav-item:hover {
  background: color-mix(in srgb, var(--lp-text-1) 6%, transparent);
  color: var(--lp-text-1);
}

.nav-item.active {
  background: var(--lp-surface-elevated);
  color: var(--lp-text-1);
  box-shadow: var(--lp-shadow-xs);
}

.nav-label {
  font-size: 11px;
  font-weight: 600;
}

/* ---------- 顶栏：居中悬浮胶囊（v2.6 §19.4；玻璃视觉来自 .lp-header，此处只调形） ----------
   v2.7 §20 R1 垂直压缩：56→48 高、12→8 上距（TREK 的导航行更矮，详情页要把它让给工作台） */
.topbar {
  position: sticky;
  top: 8px;
  z-index: var(--lp-z-bar);
  display: flex;
  align-items: center;
  gap: var(--lp-space-4);
  height: 48px;
  padding: 0 var(--lp-space-5);
  width: calc(100% - 32px);
  max-width: var(--lp-content-wide);
  margin: 8px auto 0;
  border-radius: var(--lp-radius-lg);
}

.crumbs {
  display: flex;
  align-items: baseline;
  gap: var(--lp-space-2);
  white-space: nowrap;
}

.crumb-brand {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: var(--lp-text-1);
}

.crumb-sep {
  color: var(--lp-text-faint);
}

.crumb-current {
  font-size: 13px;
  color: var(--lp-text-muted);
}

.global-search {
  flex: 1;
  max-width: 360px;
}

.topbar-end {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  margin-left: auto;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--lp-text-1);
}

/* 幽灵钮：无描边，hover 用浅面（顶栏不再出现「描边小方块」排排站） */
.logout-btn {
  padding: 6px 12px;
  border: none;
  border-radius: var(--lp-radius-sm);
  background: transparent;
  color: var(--lp-text-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.logout-btn:hover {
  background: color-mix(in srgb, var(--lp-text-1) 6%, transparent);
  color: var(--lp-text-1);
}

/* ---------- 内容与页脚 ---------- */
.content {
  padding: var(--lp-space-5);
}

/* 视口固定路由（详情工作台）：页内自管滚动，内容区不留白 */
.content.is-immersive {
  padding: 0;
}

.content-inner {
  max-width: var(--lp-content-wide);
  margin: 0 auto;
}

/* 宽容器路由（meta.wide，如详情页三栏工作台）：放开内容宽度上限 */
.content-inner.is-wide {
  max-width: none;
}

.footer {
  padding: var(--lp-space-4) var(--lp-space-3) var(--lp-space-2);
  text-align: center;
  color: var(--lp-text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.footer p {
  margin: 0;
}

/* ---------- <768px：NavRail 折为 BottomBar（同一 DOM） ---------- */
@media (max-width: 767px) {
  .shell {
    display: block;
  }

  .nav {
    position: fixed;
    inset: auto 0 0 0;
    height: auto;
    flex-direction: row;
    justify-content: center;
    gap: var(--lp-space-2);
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
    /* 底栏有内容从下方流过 → 玻璃是这里唯一被动机支撑的用法 */
    background: var(--lp-glass-bg);
    backdrop-filter: var(--lp-glass-blur);
    border-top: 1px solid var(--lp-glass-border);
    box-shadow: var(--lp-glass-shadow), var(--lp-glass-highlight);
    z-index: var(--lp-z-nav);
  }

  .nav-item {
    flex: 0 1 auto;
    padding: 6px var(--lp-space-3);
  }

  .shell-main {
    padding-bottom: 64px;
  }

  .topbar {
    top: 0;
    width: 100%;
    margin: 0;
    border-radius: 0;
    gap: var(--lp-space-2);
    padding: 0 var(--lp-space-3);
  }

  .global-search {
    display: none;
  }

  .user-name {
    display: none;
  }

  .content {
    padding: var(--lp-space-4) var(--lp-space-3);
  }
}
</style>
