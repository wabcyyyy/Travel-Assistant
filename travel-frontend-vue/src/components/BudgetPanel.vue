<template>
  <div class="budget-panel">
    <div class="total-row">
      <div>
        <div class="label">预估总价</div>
        <div class="total">￥{{ totalAmount }}</div>
      </div>
      <div v-if="budgetLimit" class="limit">
        预算上限 ￥{{ budgetLimit }}
        <el-tag :type="overBudget ? 'danger' : 'success'" size="small" style="margin-left: 6px">
          {{ overBudget ? '超预算' : '预算内' }}
        </el-tag>
      </div>
    </div>

    <div ref="chartRef" class="chart"></div>

    <div v-if="budgetList.length" class="category-list">
      <div v-for="row in budgetList" :key="row.category" class="category-row">
        <span class="dot" :style="{ background: categoryColor(row.category) }"></span>
        <span class="name">{{ row.category }}</span>
        <span class="count" v-if="row.itemCount">×{{ row.itemCount }}</span>
        <span class="amount">￥{{ row.amount }}</span>
      </div>
    </div>

    <el-divider content-position="left">每日费用</el-divider>
    <div v-for="day in dayList" :key="day.dayId" class="day-block">
      <div class="day-title">第 {{ day.dayNo }} 天（约 ￥{{ dayTotal(day) }}）</div>
      <div v-for="item in day.items" :key="item.id" class="item-line">
        <span class="item-name">{{ item.poiName }}</span>
        <span class="item-cost">
          {{ item.cost != null ? `￥${item.cost}${item.itemType === 'hotel' ? '/间/晚' : '/人'}` : '—' }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

import type { BudgetRow, DayPlan } from '../types/itinerary'

const props = defineProps<{
  budgetList: BudgetRow[]
  totalAmount: number
  budgetLimit?: number | null
  persons: number
  dayList: DayPlan[]
}>()

const CATEGORY_COLORS: Record<string, string> = {
  门票: '#b4532a',
  餐饮: '#8a9a5b',
  交通: '#d9c7a7',
  酒店: '#4a4a4a',
}

const chartRef = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const overBudget = computed(() => {
  if (!props.budgetLimit) return false
  return props.totalAmount > props.budgetLimit
})

function categoryColor(category: string) {
  return CATEGORY_COLORS[category] || '#909399'
}

function rooms(persons: number) {
  return Math.ceil(persons / 2)
}

function dayTotal(day: DayPlan) {
  return day.items.reduce((sum, item) => {
    if (item.cost == null) return sum
    if (item.itemType === 'hotel') return sum + item.cost * rooms(props.persons)
    return sum + item.cost * props.persons
  }, 0)
}

function renderChart() {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }
  const data = props.budgetList.map((row) => ({
    name: row.category,
    value: Number(row.amount),
  }))
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: ￥{c} ({d}%)' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8 },
    series: [
      {
        type: 'pie',
        radius: ['42%', '66%'],
        center: ['50%', '45%'],
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        data,
      },
    ],
  })
}

onMounted(() => {
  renderChart()
})

watch(
  () => [props.budgetList, props.totalAmount],
  () => renderChart(),
  { deep: true }
)

onBeforeUnmount(() => {
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<style scoped>
.total-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 8px;
}

.label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.total {
  font-size: 26px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.limit {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  display: flex;
  align-items: center;
}

.chart {
  height: 180px;
}

.category-list {
  margin-top: 4px;
}

.category-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 14px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.name {
  flex: 1;
}

.count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.amount {
  font-weight: 600;
}

.day-block {
  margin-bottom: 10px;
}

.day-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
}

.item-line {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--el-text-color-regular);
  padding: 1px 0;
}

.item-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}

.item-cost {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
</style>
