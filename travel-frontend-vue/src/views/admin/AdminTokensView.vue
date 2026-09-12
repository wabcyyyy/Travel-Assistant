<template>
  <div class="tokens-view">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>Token 用量</h2>
      <span class="sub">消耗趋势、场景分布与调用明细</span>
      <div class="actions">
        <el-radio-group v-model="range" @change="load">
          <el-radio-button value="1h">近 1 小时</el-radio-button>
          <el-radio-button value="24h">近 24 小时</el-radio-button>
          <el-radio-button value="7d">近 7 天</el-radio-button>
          <el-radio-button value="30d">近 30 天</el-radio-button>
        </el-radio-group>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>
    <el-alert
      v-if="usage && !usage.agentAvailable"
      title="Agent 用量服务暂不可用，以下为降级数据"
      type="warning"
      :closable="false"
      class="alert"
    />

    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.label" :xs="12" :sm="8" :md="4">
        <el-card shadow="never" class="stat-card">
          <p class="stat-label">{{ card.label }}</p>
          <p class="stat-value">{{ card.value }}</p>
          <p v-if="card.sub" class="stat-sub">{{ card.sub }}</p>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header><span class="card-title">Token 消耗趋势</span></template>
      <div ref="chartEl" class="chart" />
    </el-card>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span class="card-title">按业务场景</span></template>
          <el-table :data="usage?.by_scene ?? []" size="small" :empty-text="'暂无数据'">
            <el-table-column label="场景" min-width="100">
              <template #default="{ row }">{{ SCENE_LABELS[row.scene] ?? row.scene }}</template>
            </el-table-column>
            <el-table-column prop="calls" label="调用" width="70" class-name="num" />
            <el-table-column label="Token" width="110" class-name="num">
              <template #default="{ row }">{{ fmt(row.prompt_tokens + row.completion_tokens) }}</template>
            </el-table-column>
            <el-table-column label="占比" min-width="130">
              <template #default="{ row }">
                <el-progress :percentage="percentOf(row as CallRow)" :stroke-width="8" :show-text="false" />
              </template>
            </el-table-column>
            <el-table-column label="平均耗时" width="90" class-name="num">
              <template #default="{ row }">{{ row.avg_duration_ms }} ms</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span class="card-title">按模型</span></template>
          <el-table :data="usage?.by_model ?? []" size="small" empty-text="暂无数据">
            <el-table-column prop="model" label="模型" min-width="140" show-overflow-tooltip />
            <el-table-column prop="calls" label="调用" width="70" class-name="num" />
            <el-table-column prop="prompt_tokens" label="输入" width="90" class-name="num" />
            <el-table-column prop="completion_tokens" label="输出" width="90" class-name="num" />
            <el-table-column label="Token" width="100" class-name="num">
              <template #default="{ row }">{{ fmt(row.prompt_tokens + row.completion_tokens) }}</template>
            </el-table-column>
            <el-table-column label="平均耗时" width="90" class-name="num">
              <template #default="{ row }">{{ row.avg_duration_ms }} ms</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span class="card-title">调用明细（共 {{ usage?.calls?.total ?? 0 }} 次）</span>
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="usage?.calls?.total ?? 0"
            layout="prev, pager, next"
            @current-change="load"
          />
        </div>
      </template>
      <el-table :data="callRows" size="small" v-loading="loading" empty-text="暂无调用记录">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.ts) }}</template>
        </el-table-column>
        <el-table-column label="场景" width="100">
          <template #default="{ row }">{{ SCENE_LABELS[row.scene] ?? row.scene }}</template>
        </el-table-column>
        <el-table-column prop="model" label="模型" min-width="140" show-overflow-tooltip />
        <el-table-column prop="prompt_tokens" label="输入" width="80" class-name="num" />
        <el-table-column prop="completion_tokens" label="输出" width="80" class-name="num" />
        <el-table-column label="总 Token" width="90" class-name="num">
          <template #default="{ row }">{{ row.prompt_tokens + row.completion_tokens }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="90" class-name="num">
          <template #default="{ row }">{{ row.duration_ms }} ms</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误信息" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
// echarts 按需注册（bar/line + tooltip/legend/grid），禁全量引入，见 charts/index.ts 约定
import echarts from '../../charts'
import type { EChartsType } from '../../charts'
import { getLlmUsage, SCENE_LABELS, type LlmUsage } from '../../api'

const range = ref('24h')
const usage = ref<LlmUsage | null>(null)
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const chartEl = ref<HTMLDivElement>()
let chart: EChartsType | null = null

const cards = computed(() => {
  const s = usage.value?.summary
  return [
    { label: '总 Token', value: fmt(s?.total_tokens) },
    { label: '输入 Token', value: fmt(s?.prompt_tokens) },
    { label: '输出 Token', value: fmt(s?.completion_tokens) },
    {
      label: 'LLM 调用',
      value: fmt(s?.calls),
      sub: s?.calls ? `平均 ${fmt(Math.round(s.total_tokens / s.calls))} tok/次` : undefined,
    },
    { label: '成功率', value: s ? `${(s.success_rate * 100).toFixed(1)}%` : '-' },
    { label: '平均耗时', value: s ? fmtDuration(s.avg_duration_ms) : '-' },
  ]
})

const callRows = computed(() => usage.value?.calls?.records ?? [])

/** 调用明细行中占比计算所需字段（EP 按需后 el-table 行类型为 DefaultRow，模板内断言） */
interface CallRow {
  prompt_tokens: number
  completion_tokens: number
}

function fmt(value?: number) {
  return value == null ? '-' : Number(value).toLocaleString()
}

/** 耗时展示：<1s 用 ms，≥1s 用 s，避免数值过长换行 */
function fmtDuration(ms?: number) {
  if (ms == null) return '-'
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`
}

function fmtTime(ts: number) {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function percentOf(row: CallRow) {
  const groups = usage.value?.by_scene ?? []
  const max = Math.max(...groups.map((g) => g.prompt_tokens + g.completion_tokens), 1)
  return Math.round(((row.prompt_tokens + row.completion_tokens) / max) * 1000) / 10
}

function bucketLabel(ts: number, bucket: number) {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  if (bucket < 3600) {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  if (bucket === 3600) {
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:00`
  }
  return `${d.getMonth() + 1}-${d.getDate()}`
}

function renderChart() {
  if (!chartEl.value) return
  chart ??= echarts.init(chartEl.value)
  const u = usage.value
  const timeline = u?.timeline ?? []
  const x = timeline.map((slot) => bucketLabel(slot.ts, u?.bucket ?? 3600))
  const interval = Math.max(Math.floor(x.length / 8), 0)
  // 图表配色与主题对齐：深青绿 / 浅青 / 石板墨
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#14181f',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
    },
    legend: {
      data: ['输入 Token', '输出 Token', '调用次数'],
      top: 0,
      itemGap: 18,
      icon: 'roundRect',
      itemWidth: 14,
      itemHeight: 8,
      textStyle: { color: '#3d4451' },
    },
    grid: { left: 56, right: 56, top: 44, bottom: 30, containLabel: false },
    xAxis: {
      type: 'category',
      data: x,
      axisLabel: { interval, color: '#697180' },
      axisLine: { lineStyle: { color: '#e6e8ec' } },
    },
    yAxis: [
      { type: 'value', name: 'tok', axisLabel: { color: '#697180' }, splitLine: { lineStyle: { color: '#f1f4f6' } } },
      {
        type: 'value', name: '次', position: 'right', splitLine: { show: false },
        minInterval: 1,
        axisLabel: { color: '#697180' },
      },
    ],
    series: [
      {
        name: '输入 Token', type: 'bar', stack: 'tok', data: timeline.map((s) => s.prompt_tokens),
        itemStyle: { color: '#0f766e', borderRadius: [0, 0, 2, 2] },
      },
      {
        name: '输出 Token', type: 'bar', stack: 'tok', data: timeline.map((s) => s.completion_tokens),
        itemStyle: { color: '#87bab1', borderRadius: [2, 2, 0, 0] },
      },
      {
        name: '调用次数', type: 'line', yAxisIndex: 1, smooth: true,
        data: timeline.map((s) => s.calls),
        lineStyle: { color: '#475569', width: 2 },
        itemStyle: { color: '#475569' },
        symbolSize: 5,
      },
    ],
  })
}

async function load() {
  loading.value = true
  try {
    // 明细走服务端分页：每页 pageSize 条
    const res = await getLlmUsage(range.value, pageSize, (page.value - 1) * pageSize)
    usage.value = res.data
    renderChart()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
})

function onResize() {
  chart?.resize()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.tokens-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.alert {
  border-radius: 12px;
}

/* 场景占比条：统一主题强调色 */
.tokens-view :deep(.el-progress-bar__inner) {
  background-color: var(--lp-accent);
}

/* 统计卡：等高对齐，数值不换行 */
.tokens-view :deep(.el-col) {
  display: flex;
}

.stat-card {
  flex: 1;
  width: 100%;
}

.stat-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  height: 100%;
  padding: 18px 16px;
}

.stat-card :deep(.stat-value) {
  white-space: nowrap;
  font-size: 26px;
  font-family: var(--lp-font-display);
}

.stat-card :deep(.stat-sub) {
  margin: 0;
}

.chart {
  width: 100%;
  height: 320px;
}
</style>
