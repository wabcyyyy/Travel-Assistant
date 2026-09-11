<template>
  <div class="dashboard">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>运营总览</h2>
      <span class="sub">平台核心指标一览</span>
    </div>
    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.label" :xs="12" :sm="12" :md="6">
        <el-card
          shadow="never"
          class="stat-card"
          :class="{ clickable: card.to, accent: card.accent }"
          @click="card.to && $router.push(card.to)"
        >
          <p class="stat-label">{{ card.label }}</p>
          <p class="stat-value" :class="{ 'stat-value--link': card.accent }">{{ card.value }}</p>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="recent">
      <template #header>
        <div class="card-header">
          <span class="card-title">最新注册用户</span>
          <el-button link type="primary" @click="$router.push('/admin/users')">查看全部</el-button>
        </div>
      </template>
      <el-table :data="recentUsers" v-loading="loading" size="large">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="nickname" label="昵称" min-width="120" />
        <el-table-column prop="itineraryCount" label="行程数" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'" size="small">
              {{ row.status === 1 ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="createdAt" label="注册时间" width="180" />
        <template #empty>
          <el-empty description="还没有用户注册" :image-size="60" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getAdminStats, getAdminUsers, type AdminStats, type AdminUser } from '../../api'

const stats = ref<AdminStats | null>(null)
const recentUsers = ref<AdminUser[]>([])
const loading = ref(false)

const cards = computed(() => [
  { label: '用户总数', value: fmt(stats.value?.totalUsers), to: '/admin/users' },
  { label: '正常用户', value: fmt(stats.value?.activeUsers), to: '/admin/users' },
  { label: '禁用用户', value: fmt(stats.value?.disabledUsers), to: '/admin/users' },
  { label: '今日新增用户', value: fmt(stats.value?.todayNewUsers), to: '/admin/users' },
  { label: '行程总数', value: fmt(stats.value?.totalItineraries), to: '/admin/itineraries' },
  { label: '今日新增行程', value: fmt(stats.value?.todayNewItineraries), to: '/admin/itineraries' },
  { label: '生成中行程', value: fmt(stats.value?.generatingItineraries), to: '/admin/itineraries' },
  { label: 'Token 消耗', value: '查看仪表盘 →', to: '/admin/tokens', accent: true },
])

function fmt(value?: number) {
  return value == null ? '-' : Number(value).toLocaleString()
}

onMounted(async () => {
  loading.value = true
  try {
    const [statsRes, usersRes] = await Promise.all([
      getAdminStats(),
      getAdminUsers({ page: 1, size: 5 }),
    ])
    stats.value = statsRes.data
    recentUsers.value = usersRes.data.records
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 数值统一衬线展示层，提升质感 */
.stat-value {
  font-family: var(--lp-font-display);
}

/* 入口卡片：青绿浅底渐变，与数据卡区分 */
.stat-card.accent {
  border: 1px solid var(--lp-accent-soft);
  background: linear-gradient(135deg, #fff 60%, var(--lp-accent-soft) 160%);
}

.stat-value--link {
  color: var(--lp-accent);
  font-size: 18px;
  letter-spacing: 0.02em;
}
</style>
