<template>
  <div>
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>用户管理</h2>
      <span class="sub">搜索、查看与禁用账号</span>
    </div>
    <el-card shadow="never" class="users-card">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索用户名 / 昵称"
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
      <el-table-column prop="username" label="用户名" min-width="140" />
      <el-table-column prop="nickname" label="昵称" min-width="120" />
      <el-table-column prop="phone" label="手机号" width="130" />
      <el-table-column label="角色" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.role === 'admin'" type="warning" size="small">管理员</el-tag>
          <el-tag v-else type="info" size="small">用户</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'danger'" size="small">
            {{ row.status === 1 ? '正常' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="注册时间" width="180" />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="viewItineraries(row as AdminUser)">
            行程({{ row.itineraryCount ?? 0 }})
          </el-button>
          <el-button
            v-if="row.status === 1"
            link
            type="danger"
            :disabled="row.role === 'admin'"
            @click="onToggleStatus(row as AdminUser, 0)"
          >
            禁用
          </el-button>
          <el-button v-else link type="success" @click="onToggleStatus(row as AdminUser, 1)">启用</el-button>
          <el-button
            link
            type="danger"
            :disabled="row.role === 'admin'"
            @click="onDelete(row as AdminUser)"
          >
            删除
          </el-button>
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
import { useRouter } from 'vue-router'
import { deleteAdminUser, getAdminUsers, updateAdminUserStatus, type AdminUser } from '../../api'

const router = useRouter()

const rows = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const keyword = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await getAdminUsers({
      page: page.value,
      size: size.value,
      keyword: keyword.value || undefined,
    })
    rows.value = res.data.records
    total.value = Number(res.data.total)
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  load()
}

function viewItineraries(row: AdminUser) {
  router.push({ path: '/admin/itineraries', query: { userId: String(row.id) } })
}

async function onToggleStatus(row: AdminUser, status: 0 | 1) {
  await updateAdminUserStatus(row.id, status)
  ElMessage.success(status === 1 ? '已启用' : '已禁用')
  load()
}

async function onDelete(row: AdminUser) {
  await ElMessageBox.confirm(`确定删除用户「${row.username}」吗？删除后不可恢复。`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteAdminUser(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
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
