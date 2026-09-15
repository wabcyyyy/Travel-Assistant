<template>
  <el-dialog
    :model-value="visible"
    title="分享行程"
    width="480px"
    @update:model-value="emit('update:visible', $event)"
    @open="loadStatus"
  >
    <div v-if="loading" class="hint">加载中…</div>

    <template v-else-if="status?.shared">
      <p class="hint">只读链接，任何人打开都能看到这份行程（不含你的账号信息）。</p>
      <div class="url-row">
        <el-input :model-value="absoluteUrl" readonly />
        <el-button type="primary" @click="copy">复制</el-button>
      </div>
      <p class="hint">{{ expiresText }}</p>
      <div class="row-actions">
        <el-button :loading="saving" @click="renew">重新生成（旧链接立即失效）</el-button>
        <el-button type="danger" text :loading="saving" @click="revoke">取消分享</el-button>
      </div>
    </template>

    <template v-else>
      <p class="hint">生成只读链接后，把链接发给朋友即可查看这份行程。</p>
      <el-radio-group v-model="expireChoice" class="expire-group">
        <el-radio-button value="forever">永久</el-radio-button>
        <el-radio-button value="7">7 天</el-radio-button>
        <el-radio-button value="30">30 天</el-radio-button>
      </el-radio-group>
      <div class="row-actions">
        <el-button type="primary" :loading="saving" @click="create">生成链接</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { createShare, getShareStatus, removeShare, type ShareStatus } from '../../api/share'

const props = defineProps<{
  visible: boolean
  itineraryId: number
}>()

const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const loading = ref(false)
const saving = ref(false)
const status = ref<ShareStatus | null>(null)
// el-radio-button 的 value 不接受 null，用哨兵字符串；出参时再映射回 7|30|null
const expireChoice = ref<'forever' | '7' | '30'>('7')

function expireDays(): 7 | 30 | null {
  if (expireChoice.value === 'forever') return null
  return expireChoice.value === '30' ? 30 : 7
}

const absoluteUrl = computed(() =>
  status.value?.shareUrl ? `${location.origin}${status.value.shareUrl}` : '',
)
const expiresText = computed(() => {
  const value = status.value?.shareExpiresAt
  return value ? `过期时间：${value.replace('T', ' ')}` : '永久有效'
})

async function loadStatus(): Promise<void> {
  loading.value = true
  try {
    const res = await getShareStatus(props.itineraryId)
    status.value = res.data
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function create(): Promise<void> {
  saving.value = true
  try {
    await createShare(props.itineraryId, expireDays())
    await loadStatus()
  } catch {
    /* 拦截器已提示（归档行程不可分享等） */
  } finally {
    saving.value = false
  }
}

async function renew(): Promise<void> {
  saving.value = true
  try {
    await createShare(props.itineraryId, expireDays())
    await loadStatus()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

async function revoke(): Promise<void> {
  try {
    await ElMessageBox.confirm('取消后原链接立即失效，确认取消分享？', '取消分享', { type: 'warning' })
  } catch {
    return
  }
  saving.value = true
  try {
    await removeShare(props.itineraryId)
    ElMessage.success('已取消分享')
    await loadStatus()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

async function copy(): Promise<void> {
  const url = absoluteUrl.value
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制')
  } catch {
    // 剪贴板不可用（非安全上下文等）：把链接直接展示出来让用户手动复制
    ElMessage.info(url)
  }
}
</script>

<style scoped>
.hint {
  margin: var(--lp-space-2) 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.url-row {
  display: flex;
  gap: var(--lp-space-2);
}

.expire-group {
  margin: var(--lp-space-2) 0;
}

.row-actions {
  display: flex;
  gap: var(--lp-space-2);
  margin-top: var(--lp-space-3);
}
</style>
