<template>
  <div class="agent-view">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>Agent 监控</h2>
      <span class="sub">运行指标、稳定性与失败轨迹</span>
      <div class="actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>
    <el-alert
      v-if="metrics && !metrics.agentAvailable"
      title="Agent 指标服务暂不可用，以下为降级数据"
      type="warning"
      :closable="false"
      class="alert"
    />

    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.label" :span="6">
        <el-card shadow="never" class="stat-card">
          <p class="stat-label">{{ card.label }}</p>
          <p class="stat-value">{{ card.value }}</p>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span class="card-title">调用量</span></template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="运行总数">{{ metrics?.runs ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="成功运行">{{ metrics?.successes ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="工具调用次数">{{ metrics?.tool_calls ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="降级运行数">{{ metrics?.degraded_runs ?? '-' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><span class="card-title">稳定性</span></template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="平均事件耗时">
              {{ metrics ? metrics.avg_event_latency_ms.toFixed(1) + ' ms' : '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="成功率">{{ pct(metrics?.success_rate) }}</el-descriptions-item>
            <el-descriptions-item label="降级率">{{ pct(metrics?.degraded_rate) }}</el-descriptions-item>
            <el-descriptions-item label="失败率">{{ pct(metrics?.failure_rate) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header><span class="card-title">最近失败轨迹</span></template>
      <el-empty v-if="!metrics?.recent_failures?.length" description="暂无失败记录" :image-size="60" />
      <el-collapse v-else>
        <el-collapse-item v-for="f in metrics.recent_failures" :key="f.run_id" :name="f.run_id">
          <template #title>
            <span class="run-id">{{ f.run_id }}</span>
            <el-tag type="danger" size="small" class="ml8">{{ firstError(f) }}</el-tag>
          </template>
          <el-table :data="f.events" size="small">
            <el-table-column prop="kind" label="类型" width="110" />
            <el-table-column prop="name" label="事件" min-width="180" />
            <el-table-column prop="status" label="状态" width="90" />
            <el-table-column prop="error" label="错误信息" min-width="220" show-overflow-tooltip />
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getAgentMetrics, type AgentMetrics } from '../../api'

const metrics = ref<AgentMetrics | null>(null)
const loading = ref(false)

const cards = computed(() => [
  { label: '运行总数', value: metrics.value?.runs ?? '-' },
  { label: '成功率', value: pct(metrics.value?.success_rate) },
  { label: '失败数', value: metrics.value?.failures ?? '-' },
  { label: '平均事件耗时', value: metrics.value ? `${metrics.value.avg_event_latency_ms.toFixed(0)} ms` : '-' },
])

function pct(value?: number) {
  return value == null ? '-' : `${(value * 100).toFixed(1)}%`
}

function firstError(f: { events: { error: string }[] }) {
  return f.events?.find((e) => e.error)?.error || '失败'
}

async function load() {
  loading.value = true
  try {
    const res = await getAgentMetrics()
    metrics.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.agent-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.alert {
  border-radius: 12px;
}

.run-id {
  font-family: monospace;
  font-size: 12px;
}

.ml8 {
  margin-left: 8px;
}
</style>
