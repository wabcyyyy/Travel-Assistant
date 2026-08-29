<template>
  <div class="trips">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>我的行程</h2>
      <span class="sub">共 {{ list.length }} 个行程</span>
    </div>
    <el-card shadow="never">
      <el-table v-if="list.length" :data="list" style="width: 100%" class="clickable-table" @row-click="goDetail">
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" min-width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 2 ? 'success' : row.status === 1 ? 'warning' : 'danger'" size="small">
              {{ row.status === 2 ? '已生成' : row.status === 1 ? '生成中' : '生成失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="city" label="目的地" min-width="90" show-overflow-tooltip />
        <el-table-column label="日期" min-width="170">
          <template #default="{ row }">
            {{ row.startDate ? row.startDate : '—' }} ~ {{ row.endDate ? row.endDate : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="天数/人数" min-width="100">
          <template #default="{ row }">{{ row.days }} 天 / {{ row.persons }} 人</template>
        </el-table-column>
        <el-table-column label="预估总价" min-width="100">
          <template #default="{ row }">￥{{ row.totalAmount }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="140">
          <template #default="{ row }">{{ formatCreatedAt(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="$router.push(`/trips/${row.id}`)">查看</el-button>
            <el-button link type="danger" @click.stop="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无行程，先去生成一个吧">
        <el-button type="primary" @click="$router.push('/generate')">去生成行程</el-button>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import { deleteItinerary, getItineraryList } from '../api'
import type { ItinerarySummary } from '../types/itinerary'

const $router = useRouter()
const list = ref<ItinerarySummary[]>([])

function formatCreatedAt(value: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

function goDetail(row: ItinerarySummary) {
  void $router.push(`/trips/${row.id}`)
}

async function load() {
  const res = await getItineraryList()
  list.value = res.data
}

async function onDelete(row: ItinerarySummary) {
  await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除确认', { type: 'warning' })
  await deleteItinerary(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.trips {
  max-width: 1200px;
  margin: 0 auto;
}

.clickable-table :deep(tbody tr) {
  cursor: pointer;
}
</style>
