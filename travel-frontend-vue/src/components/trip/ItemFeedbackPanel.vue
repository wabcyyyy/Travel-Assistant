<template>
  <div v-if="enabled && item?.id" class="fb">
    <div class="fb-row">
      <span class="fb-q">这条安排靠谱吗？</span>
      <template v-if="mine">
        <span class="fb-state" :class="{ 'is-wrong': mine.value === 'wrong' }">{{ stateText }}</span>
        <button type="button" class="fb-btn" @click="openEdit">修改</button>
        <button type="button" class="fb-btn" :disabled="busy" @click="revoke">撤销</button>
      </template>
      <template v-else>
        <button type="button" class="fb-btn" :disabled="busy" @click="submitRight">对</button>
        <button type="button" class="fb-btn" :disabled="busy" @click="openEdit">错</button>
      </template>
    </div>
    <form v-if="formOpen" class="fb-form" @submit.prevent="submitWrong">
      <p class="fb-form-title">哪里不对？</p>
      <div class="fb-reasons" role="radiogroup" aria-label="错误原因">
        <button
          v-for="(label, key) in REASON_LABELS"
          :key="key"
          type="button"
          role="radio"
          class="fb-chip"
          :class="{ 'is-active': reason === key }"
          :aria-checked="reason === key ? 'true' : 'false'"
          @click="reason = key"
        >
          {{ label }}
        </button>
      </div>
      <AppTextarea
        v-model="note"
        class="fb-note"
        :rows="2"
        :maxlength="200"
        placeholder="补充说明（可选，200 字内）"
        aria-label="备注"
      />
      <div class="fb-form-foot">
        <span class="fb-count">{{ note.length }}/200</span>
        <button type="button" class="fb-btn" @click="formOpen = false">取消</button>
        <button type="submit" class="fb-btn is-primary" :disabled="!reason || busy">提交</button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { fetchMyFeedback, revokeFeedback, submitFeedback, type FeedbackReason, type FeedbackVO } from '../../api/feedback'
import { useItineraryStore } from '../../store/itinerary'
import AppTextarea from '../ui/AppTextarea.vue'
import type { TripItem } from '../../types/itinerary'

// 条目对/错反馈入口（C3.5，SPEC §1/§3 推荐列）：对=一键直提；错=原因六选一 + 可选备注。
// addon 关闭（回显 404）或读取失败时整块隐藏——回显读取 skipErrorMessage，不打断行程页。
// 提交/撤销失败由 request 层统一弹 toast，这里只吞异常避免 unhandled rejection。
const props = defineProps<{ item: TripItem | null }>()

const store = useItineraryStore()
const { detail } = storeToRefs(store)

// 前端中文映射（SPEC §1：英文枚举入库）
const REASON_LABELS: Record<FeedbackReason, string> = {
  wrong_location: '坐标/位置错',
  wrong_time: '时间不合理',
  wrong_price: '价格离谱',
  not_interested: '不感兴趣',
  closed: '停业/歇业',
  other: '其他',
}

const enabled = ref(false)
const busy = ref(false)
const formOpen = ref(false)
const reason = ref<FeedbackReason | null>(null)
const note = ref('')
const feedbackMap = ref(new Map<number, FeedbackVO>())

const mine = computed(() => (props.item?.id ? feedbackMap.value.get(props.item.id) ?? null : null))

const stateText = computed(() => {
  const row = mine.value
  if (!row) return ''
  if (row.value === 'right') return '已标：对'
  return `已标：错·${row.reason ? REASON_LABELS[row.reason] : '其他'}`
})

async function load() {
  const itineraryId = detail.value?.id
  if (!itineraryId) return
  try {
    const res = await fetchMyFeedback(itineraryId)
    feedbackMap.value = new Map(res.data.feedbacks.map((row) => [row.itemId, row]))
    enabled.value = true
  } catch {
    enabled.value = false
  }
}

watch(() => detail.value?.id, load, { immediate: true })

function openEdit() {
  const row = mine.value
  reason.value = row?.reason ?? null
  note.value = row?.note ?? ''
  formOpen.value = true
}

async function submitRight() {
  await send({ value: 'right', reason: null, note: null })
  formOpen.value = false
}

async function submitWrong() {
  if (!reason.value) return
  await send({ value: 'wrong', reason: reason.value, note: note.value.trim() || null })
  formOpen.value = false
}

async function send(body: { value: 'right' | 'wrong'; reason: FeedbackReason | null; note: string | null }) {
  const itineraryId = detail.value?.id
  const itemId = props.item?.id
  if (!itineraryId || !itemId) return
  busy.value = true
  try {
    const res = await submitFeedback(itineraryId, { itemId, ...body })
    feedbackMap.value = new Map(feedbackMap.value).set(itemId, res.data)
  } catch {
    // request 层已 toast；保持现状让用户重试
  } finally {
    busy.value = false
  }
}

async function revoke() {
  const itineraryId = detail.value?.id
  const itemId = props.item?.id
  if (!itineraryId || !itemId) return
  busy.value = true
  try {
    await revokeFeedback(itineraryId, itemId)
    const next = new Map(feedbackMap.value)
    next.delete(itemId)
    feedbackMap.value = next
    formOpen.value = false
  } catch {
    // 同上：toast 已弹，状态不动
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.fb {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--lp-edge-faint);
}

.fb-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.fb-q {
  margin-right: auto;
  font-size: 12.5px;
  color: var(--lp-text-muted);
}

.fb-state {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--lp-accent-hover);
}

.fb-state.is-wrong {
  color: var(--lp-danger);
}

.fb-btn {
  padding: 4px 12px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.fb-btn:hover:not(:disabled) {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.fb-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.fb-btn.is-primary {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
}

.fb-form {
  margin-top: 8px;
}

.fb-form-title {
  margin: 0 0 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--lp-text-2);
}

.fb-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fb-chip {
  padding: 3px 10px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.fb-chip.is-active {
  border-color: var(--lp-accent);
  background: var(--lp-accent-subtle);
  color: var(--lp-accent-hover);
}

.fb-note {
  width: 100%;
  margin-top: 8px;
  padding: 6px 8px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-xs);
  background: var(--lp-surface-card);
  color: var(--lp-text-1);
  font-size: 12.5px;
  line-height: 1.5;
  resize: vertical;
}

.fb-form-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}

.fb-count {
  margin-right: auto;
  font-family: var(--lp-font-mono);
  font-size: 11px;
  color: var(--lp-text-faint);
}
</style>
