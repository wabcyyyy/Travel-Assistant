<template>
  <el-drawer
    :model-value="visible"
    title="版本历史"
    size="440px"
    @update:model-value="emit('update:visible', $event)"
    @open="loadVersions"
  >
    <div v-loading="loading" class="version-body">
      <p class="hint">
        服务端快照链：每次写操作前后各一条；回滚本身也会再打一条快照（可再回滚）。
        勾选 2 条看差异，勾选 1 条可恢复。
      </p>

      <ul class="ver-list">
        <li v-for="version in versions" :key="version.id">
          <label class="ver-row" :class="{ active: selected.includes(version.id) }">
            <input
              type="checkbox"
              :checked="selected.includes(version.id)"
              @change="toggle(version.id)"
            />
            <span class="ver-no">v{{ version.versionNo }}</span>
            <span class="ver-op">{{ versionOperationLabel(version.operation) }}</span>
            <span class="ver-sum">{{ version.summary || '无摘要' }}</span>
            <span class="ver-time">{{ formatTime(version.createdAt) }}</span>
          </label>
        </li>
      </ul>
      <p v-if="!versions.length && !loading" class="hint">暂无版本快照</p>

      <div class="row-actions">
        <el-button :disabled="selected.length !== 2" :loading="diffing" @click="loadDiff">
          对比所选两版
        </el-button>
        <el-button
          type="primary"
          :disabled="selected.length !== 1"
          :loading="restoring"
          @click="restore"
        >
          恢复到此版本
        </el-button>
      </div>

      <div v-if="diff" class="diff">
        <p class="hint">v{{ diffRange.from }} → v{{ diffRange.to }}：{{ diff.changes.length }} 处变更</p>
        <ul class="diff-list">
          <li v-for="(change, index) in diff.changes" :key="`${change.type}-${change.key}-${index}`">
            <span class="diff-type" :class="`is-${change.type}`">{{ CHANGE_LABELS[change.type] }}</span>
            <span class="diff-key">{{ change.key }}</span>
            <span class="diff-val">{{ brief(change.before) }} → {{ brief(change.after) }}</span>
          </li>
        </ul>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { diffVersions, listVersions, restoreVersion, type VersionDiff, type VersionSummary } from '../../api/versions'
import { versionOperationLabel } from '../../constants/versionOperation'
import type { ItineraryDetail } from '../../types/itinerary'

const props = defineProps<{
  visible: boolean
  itineraryId: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  restored: [detail: ItineraryDetail]
}>()

const CHANGE_LABELS: Record<string, string> = {
  added: '新增',
  removed: '移除',
  updated: '修改',
}

const loading = ref(false)
const diffing = ref(false)
const restoring = ref(false)
const versions = ref<VersionSummary[]>([])
const selected = ref<number[]>([])
const diff = ref<VersionDiff | null>(null)
const diffRange = ref<{ from: number; to: number }>({ from: 0, to: 0 })

async function loadVersions(): Promise<void> {
  loading.value = true
  selected.value = []
  diff.value = null
  try {
    const res = await listVersions(props.itineraryId)
    versions.value = res.data ?? []
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

/** 最多勾选两条：已满时替换掉较早的一条，保持「最近两次选择」的直觉 */
function toggle(id: number): void {
  const index = selected.value.indexOf(id)
  if (index >= 0) {
    selected.value.splice(index, 1)
    return
  }
  if (selected.value.length >= 2) selected.value.shift()
  selected.value.push(id)
}

async function loadDiff(): Promise<void> {
  if (selected.value.length !== 2 || diffing.value) return
  const [a, b] = selected.value
    .map((id) => versions.value.find((item) => item.id === id))
    .filter((item): item is VersionSummary => item != null)
    .sort((x, y) => x.versionNo - y.versionNo)
  if (!a || !b) return
  diffing.value = true
  try {
    const res = await diffVersions(props.itineraryId, a.id, b.id)
    diff.value = res.data
    diffRange.value = { from: a.versionNo, to: b.versionNo }
  } catch {
    /* 拦截器已提示 */
  } finally {
    diffing.value = false
  }
}

async function restore(): Promise<void> {
  const target = versions.value.find((item) => item.id === selected.value[0])
  if (!target || restoring.value) return
  try {
    await ElMessageBox.confirm(
      `恢复到 v${target.versionNo}（${versionOperationLabel(target.operation)}）？当前状态会先自动打一条快照，可再回滚。`,
      '恢复版本',
      { type: 'warning' },
    )
  } catch {
    return
  }
  restoring.value = true
  try {
    const res = await restoreVersion(props.itineraryId, target.id)
    ElMessage.success('已恢复，且已生成一条可回滚的新快照')
    emit('restored', res.data)
    await loadVersions()
  } catch {
    /* 拦截器已提示 */
  } finally {
    restoring.value = false
  }
}

function formatTime(value: string): string {
  return value ? value.replace('T', ' ').slice(0, 16) : ''
}

function brief(value: unknown): string {
  if (value == null) return '∅'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}
</script>

<style scoped>
.version-body {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-2);
}

.hint {
  margin: 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.ver-list {
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--lp-edge-faint);
}

.ver-row {
  display: grid;
  grid-template-columns: auto auto auto 1fr auto;
  align-items: center;
  gap: var(--lp-space-2);
  padding: var(--lp-space-2) 4px;
  border-bottom: 1px solid var(--lp-edge-faint);
  cursor: pointer;
  font-size: 13px;
}

.ver-row.active {
  background: var(--lp-accent-subtle);
}

.ver-no {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  color: var(--lp-text-1);
}

.ver-op {
  color: var(--lp-accent-hover);
  font-weight: 600;
}

.ver-sum {
  color: var(--lp-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ver-time {
  font-size: var(--lp-text-caption);
  color: var(--lp-text-faint);
  font-variant-numeric: tabular-nums;
}

.row-actions {
  display: flex;
  gap: var(--lp-space-2);
}

.diff-list {
  margin: var(--lp-space-2) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.diff-list li {
  display: flex;
  gap: var(--lp-space-2);
  font-size: var(--lp-text-caption);
  color: var(--lp-text-2);
}

.diff-type {
  flex: none;
  font-weight: 700;
}

.diff-type.is-added {
  color: var(--lp-success);
}

.diff-type.is-removed {
  color: var(--lp-danger);
}

.diff-type.is-updated {
  color: var(--lp-warning);
}

.diff-key {
  flex: none;
  color: var(--lp-text-muted);
}

.diff-val {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
