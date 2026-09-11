<template>
  <div class="admin-layout">
    <el-aside width="200px" class="admin-aside">
      <div class="lp-logo admin-brand">
        <span class="mark"></span>
        <span class="zh">管理后台</span>
        <span class="en">Admin</span>
      </div>
      <el-menu :default-active="activeMenu" :router="true" class="admin-menu">
        <el-menu-item-group>
          <template #title><span class="menu-group">概览</span></template>
          <el-menu-item index="/admin">
            <el-icon><Odometer /></el-icon>
            <span>数据概览</span>
          </el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group>
          <template #title><span class="menu-group">数据</span></template>
          <el-menu-item index="/admin/tokens">
            <el-icon><DataLine /></el-icon>
            <span>Token 仪表盘</span>
          </el-menu-item>
          <el-menu-item index="/admin/itineraries">
            <el-icon><Guide /></el-icon>
            <span>行程管理</span>
          </el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group>
          <template #title><span class="menu-group">账号</span></template>
          <el-menu-item index="/admin/users">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group>
          <template #title><span class="menu-group">系统</span></template>
          <el-menu-item index="/admin/agent">
            <el-icon><Monitor /></el-icon>
            <span>Agent 监控</span>
          </el-menu-item>
        </el-menu-item-group>
      </el-menu>
    </el-aside>
    <div class="admin-content">
      <router-view />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { DataLine, Guide, Monitor, Odometer, User } from '@element-plus/icons-vue'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style scoped>
.admin-layout {
  display: flex;
  gap: 20px;
  min-height: calc(100vh - 108px);
}

.admin-aside {
  border-radius: 16px;
  background: var(--lp-surface);
  border: 1px solid var(--lp-border);
  box-shadow: var(--lp-shadow-xs);
  padding: 16px 0;
  height: fit-content;
  position: sticky;
  top: 76px;
}

/* 后台标识：复用主站 logo 结构，尺寸更收敛 */
.admin-brand {
  padding: 4px 20px 14px;
}

.admin-brand .zh {
  font-size: 15px;
}

.admin-brand .en {
  letter-spacing: 0.12em;
}

.admin-menu {
  border-right: none;
}

/* 菜单分组小标题 */
.admin-menu :deep(.el-menu-item-group__title) {
  padding: 12px 20px 4px 30px;
}

.menu-group {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--lp-muted);
}

.admin-menu :deep(.el-menu-item) {
  margin: 2px 10px;
  border-radius: 8px;
  height: 42px;
  color: var(--lp-ink-soft);
  transition:
    background 0.15s ease,
    color 0.15s ease,
    box-shadow 0.15s ease;
}

.admin-menu :deep(.el-menu-item:hover) {
  background: var(--lp-sand);
}

.admin-menu :deep(.el-menu-item.is-active) {
  background: var(--lp-accent-soft);
  color: var(--lp-accent-hover);
  font-weight: 700;
  box-shadow: inset 3px 0 0 0 var(--lp-accent);
}

.admin-content {
  flex: 1;
  min-width: 0;
}

@media (max-width: 860px) {
  .admin-layout {
    flex-direction: column;
    gap: 12px;
  }

  .admin-aside {
    position: static;
    width: 100% !important;
    height: auto;
  }

  .admin-menu {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
  }

  .admin-menu :deep(.el-menu-item-group) {
    width: auto;
  }

  .admin-menu :deep(.el-menu-item-group__title) {
    display: none;
  }

  .admin-menu :deep(.el-menu-item) {
    margin: 2px;
    height: 40px;
    line-height: 40px;
  }

  .admin-brand .en {
    display: none;
  }
}
</style>
