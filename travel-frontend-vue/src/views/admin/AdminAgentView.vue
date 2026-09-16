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

    <div class="addon-card">
      <div class="addon-head">
        <span class="card-title">功能开关</span>
        <span class="addon-sub">运行时能力开关：关闭后对应 API 不可见、工具面同步收起</span>
      </div>
      <div v-for="addon in addons" :key="addon.key" class="addon-row">
        <div class="addon-info">
          <span class="addon-label">{{ addon.label }}</span>
          <code class="addon-key">{{ addon.key }}</code>
        </div>
        <button
          type="button"
          class="addon-toggle"
          :class="{ 'is-on': addon.enabled }"
          :disabled="addonBusy === addon.key"
          role="switch"
          :aria-checked="addon.enabled"
          :aria-label="addon.label"
          @click="toggleAddon(addon)"
        >
          <span class="addon-knob"></span>
          <span class="addon-state">{{ addon.enabled ? '已启用' : '已停用' }}</span>
        </button>
      </div>
      <p v-if="addonError" class="addon-error">{{ addonError }}</p>
    </div>

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
import { getAddons, getAgentMetrics, setAddon, type AddonInfo, type AgentMetrics } from '../../api'

const metrics = ref<AgentMetrics | null>(null)
const loading = ref(false)
const addons = ref<AddonInfo[]>([])
const addonBusy = ref('')
const addonError = ref('')

async function loadAddons() {
  try {
    const res = await getAddons()
    addons.value = res.data.addons
  } catch {
    addonError.value = '功能开关加载失败'
  }
}

async function toggleAddon(addon: AddonInfo) {
  addonBusy.value = addon.key
  addonError.value = ''
  try {
    const res = await setAddon(addon.key, !addon.enabled)
    addon.enabled = res.data.enabled
  } catch {
    addonError.value = `切换 ${addon.label} 失败`
  } finally {
    addonBusy.value = ''
  }
}

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

onMounted(() => {
  load()
  loadAddons()
})
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
  font-family: var(--lp-font-data);
  font-size: 12px;
}

.ml8 {
  margin-left: 8px;
}
</style>

<style scoped>
/* 功能开关（G-3.1）：自定义控件——EP 使用数在 allowlist 冻结，本卡零新增 el-* */
.addon-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  background: var(--lp-surface-card);
  border: 1px solid var(--lp-surface-3);
  border-radius: var(--lp-radius-md);
}

.addon-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.addon-sub {
  font-size: 12px;
  color: var(--lp-text-muted);
}

.addon-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px;
  border-top: 1px solid var(--lp-surface-2);
}

.addon-info {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.addon-label {
  font-weight: 600;
  color: var(--lp-text-1);
}

.addon-key {
  font-size: 12px;
  color: var(--lp-text-faint);
}

.addon-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border: 1px solid var(--lp-surface-3);
  border-radius: 999px;
  background: var(--lp-surface-2);
  color: var(--lp-text-2);
  cursor: pointer;
}

.addon-toggle.is-on {
  background: var(--lp-accent-subtle);
  border-color: var(--lp-accent);
}

.addon-toggle:disabled {
  cursor: wait;
  opacity: 0.6;
}

.addon-knob {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--lp-text-faint);
}

.addon-toggle.is-on .addon-knob {
  background: var(--lp-accent);
}

.addon-state {
  font-size: 12px;
}

.addon-error {
  margin: 0;
  font-size: 12px;
  color: var(--lp-danger);
}
</style>
