<template>
  <div class="trips">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>我的行程</h2>
      <span class="sub">共 {{ list.length }} 个行程</span>
    </div>
    <el-card shadow="never">
      <el-table v-if="list.length" :data="list" style="width: 100%">
        <el-table-column prop="title" label="标题" min-width="160" />
        <el-table-column prop="city" label="目的地" width="100" />
        <el-table-column label="日期" width="180">
          <template #default="{ row }">
            {{ row.startDate ? row.startDate : '—' }} ~ {{ row.endDate ? row.endDate : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="天数/人数" width="110">
          <template #default="{ row }">{{ row.days }} 天 / {{ row.persons }} 人</template>
        </el-table-column>
        <el-table-column label="预估总价" width="120">
          <template #default="{ row }">￥{{ row.totalAmount }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push(`/trips/${row.id}`)">查看</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
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

import { deleteItinerary, getItineraryList } from '../api'
import type { ItinerarySummary } from '../types/itinerary'

const list = ref<ItinerarySummary[]>([])

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
  max-width: 960px;
  margin: 0 auto;
}
</style>