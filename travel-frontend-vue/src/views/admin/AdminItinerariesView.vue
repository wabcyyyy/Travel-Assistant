<template>
  <div>
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>行程管理</h2>
      <span class="sub">按用户查看全部行程</span>
    </div>
    <el-card shadow="never" class="card">
    <div class="toolbar">
      <el-select
        v-model="selectedUserId"
        placeholder="全部用户"
        clearable
        filterable
        class="user-select"
        @change="onSearch"
      >
        <el-option
          v-for="u in userOptions"
          :key="u.id"
          :label="`${u.username}${u.nickname ? ` (${u.nickname})` : ''}`"
          :value="u.id"
        />
      </el-select>
      <el-select v-model="status" placeholder="全部状态" clearable class="status-select" @change="onSearch">
        <el-option label="草稿(生成中)" :value="1" />
        <el-option label="已生成" :value="2" />
        <el-option label="已取消" :value="3" />
      </el-select>
      <el-input
        v-model="keyword"
        placeholder="搜索标题 / 城市"
        clearable
        class="search"
        @keyup.enter="onSearch"
        @clear="onSearch"
      >
        <template #append>
          <el-button @click="onSearch">搜索</el-button>
        </template>
      </el-input>
    </div>

    <el-table :data="rows" v-loading="loading" size="large">
      <el-table-column prop="id" label="ID" width="70" class-name="num" />
      <el-table-column prop="userId" label="用户ID" width="80" class-name="num" />
      <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
      <el-table-column prop="city" label="城市" width="100" />
      <el-table-column label="日期" width="200">
        <template #default="{ row }">
          {{ row.startDate || '-' }} ~ {{ row.endDate || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="days" label="天数" width="70" class-name="num" />
      <el-table-column prop="persons" label="人数" width="70" class-name="num" />
      <el-table-column label="预算" width="100" class-name="num">
        <template #default="{ row }">
          {{ row.budget == null ? '-' : `¥${row.budget}` }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="创建时间" width="180" />
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="onDelete(row as AdminItinerary)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @size-change="load"
        @current-change="load"
      />
    </div>
  </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  deleteAdminItinerary,
  getAdminItineraries,
  getAdminUsers,
  type AdminItinerary,
  type AdminUser,
} from '../../api'

const route = useRoute()
const rows = ref<AdminItinerary[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const keyword = ref('')
const status = ref<number | undefined>(undefined)
const selectedUserId = ref<number | undefined>(
  route.query.userId ? Number(route.query.userId) : undefined,
)
const userOptions = ref<AdminUser[]>([])
const loading = ref(false)

function statusLabel(status: number) {
  if (status === 1) return '草稿(生成中)'
  if (status === 2) return '已生成'
  return '已取消'
}

function statusType(status: number): 'warning' | 'success' | 'info' {
  if (status === 1) return 'warning'
  if (status === 2) return 'success'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const res = await getAdminItineraries({
      page: page.value,
      size: size.value,
      keyword: keyword.value || undefined,
      status: status.value,
      userId: selectedUserId.value,
    })
    rows.value = res.data.records
    total.value = Number(res.data.total)
  } finally {
    loading.value = false
  }
}

async function loadUserOptions() {
  const res = await getAdminUsers({ page: 1, size: 500 })
  userOptions.value = res.data.records
}

function onSearch() {
  page.value = 1
  load()
}

async function onDelete(row: AdminItinerary) {
  await ElMessageBox.confirm(
    `确定删除行程「${row.title}」（ID: ${row.id}）吗？用户侧将不可见。`,
    '删除确认',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await deleteAdminItinerary(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(() => {
  loadUserOptions()
  load()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-bottom: 16px;
}

.user-select {
  width: 220px;
  margin-right: auto;
}

.status-select {
  width: 150px;
}

.search {
  width: 280px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
