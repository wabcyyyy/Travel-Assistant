<template>
  <div class="trip-detail" v-loading="loading">
    <el-card v-if="detail" shadow="never" class="head">
      <div class="head-info">
        <h2>{{ detail.title }}</h2>
        <p>
          {{ detail.city }} · {{ detail.days }} 天 {{ detail.persons }} 人
          <template v-if="detail.preferences"> · 偏好：{{ detail.preferences }}</template>
        </p>
        <p v-if="detail.startDate">日期：{{ detail.startDate }} ~ {{ detail.endDate }}</p>
      </div>
      <div class="head-actions">
        <el-button @click="$router.back()">返回</el-button>
        <el-button @click="$router.push('/generate')">重新生成</el-button>
      </div>
    </el-card>

    <el-row v-if="detail" :gutter="16">
      <el-col :span="16">
        <el-collapse v-model="activeDays">
          <el-collapse-item v-for="day in detail.dayList" :key="day.dayId" :name="day.dayNo">
            <template #title>
              <span class="day-title">
                第 {{ day.dayNo }} 天
                <el-tag v-if="day.travelDate" size="small">{{ day.travelDate }}</el-tag>
                <span v-if="day.note" class="day-note">{{ day.note }}</span>
              </span>
            </template>
            <el-timeline>
              <el-timeline-item
                v-for="item in day.items"
                :key="item.id"
                :timestamp="timeRange(item)"
                placement="top"
              >
                <div class="item-row">
                  <div class="item-main">
                    <el-tag :type="tagType(item.itemType)" size="small">{{ typeLabel(item.itemType) }}</el-tag>
                    <span class="item-name">{{ item.poiName }}</span>
                    <el-tag v-if="item.tag" size="small" effect="plain">{{ item.tag }}</el-tag>
                  </div>
                  <div class="item-sub">
                    <span v-if="item.durationMin">约 {{ item.durationMin }} 分钟</span>
                    <span v-if="item.cost != null">￥{{ item.cost }}/人</span>
                    <span v-if="item.remark">{{ item.remark }}</span>
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </el-collapse-item>
        </el-collapse>
      </el-col>
      <el-col :span="8">
        <el-card shadow="never">
          <template #header>
            <span>预算明细</span>
          </template>
          <el-table :data="detail.budgetList" size="small">
            <el-table-column prop="category" label="分类" />
            <el-table-column label="金额">
              <template #default="{ row }">￥{{ row.amount }}</template>
            </el-table-column>
          </el-table>
          <div class="total">
            预估总价：<b>￥{{ detail.totalAmount }}</b>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getItineraryDetail } from '../api'
import type { ItineraryDetail, TripItem } from '../types/itinerary'

const route = useRoute()
const loading = ref(false)
const detail = ref<ItineraryDetail | null>(null)
const activeDays = ref<number[]>([])

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '餐饮',
  hotel: '酒店',
  transport: '交通',
}

const TYPE_TAG: Record<string, string> = {
  attraction: 'primary',
  food: 'warning',
  hotel: 'success',
  transport: 'info',
}

const activeAll = computed(() =>
  detail.value ? detail.value.dayList.map((d) => d.dayNo) : []
)

function typeLabel(type: string) {
  return TYPE_LABEL[type] || type
}

function tagType(type: string) {
  return (TYPE_TAG[type] || 'info') as 'primary' | 'warning' | 'success' | 'info'
}

function timeRange(item: TripItem) {
  if (item.startTime && item.endTime) return `${item.startTime} ~ ${item.endTime}`
  return item.startTime || ''
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await getItineraryDetail(route.params.id as string)
    detail.value = res.data
    activeDays.value = activeAll.value
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.trip-detail {
  max-width: 1100px;
  margin: 0 auto;
}

.head {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.head-info h2 {
  margin: 0 0 8px;
}

.head-info p {
  margin: 4px 0;
  color: var(--el-text-color-secondary);
}

.day-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.day-note {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.item-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.item-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.item-name {
  font-weight: 600;
}

.item-sub {
  display: flex;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.total {
  margin-top: 12px;
  text-align: right;
  font-size: 15px;
}
</style>