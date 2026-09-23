<template>
  <div class="create-trip">
    <section class="intent-block">
      <label class="field-label" for="trip-intent">旅行意图</label>
      <div class="intent-write">
        <AppTextarea
          id="trip-intent"
          v-model="intent"
          :rows="4"
          aria-label="旅行意图"
          placeholder="一句话说清这趟旅行最想要什么&#10;例如：成都 4 日，以美食和市井街区为主，节奏松弛"
        />
      </div>
      <div class="intent-foot">
        <div class="intent-examples">
          <button
            v-for="e in INTENT_EXAMPLES"
            :key="e"
            type="button"
            class="ghost-chip"
            @click="applyIntentExample(e)"
          >
            {{ e }}
          </button>
        </div>
        <span class="intent-counter" :class="{ over: intent.length > INTENT_MAX }">
          {{ intent.length }}/{{ INTENT_MAX }}
        </span>
      </div>
    </section>

    <section class="manifest">
      <h2 class="section-title">行程要素</h2>
      <div class="manifest-grid">
        <div class="man-cell">
          <span class="man-k">目的地</span>
          <AppInput v-model="form.city" placeholder="城市" aria-label="目的地" />
        </div>
        <div class="man-cell">
          <span class="man-k">日期</span>
          <div class="date-pair">
            <AppInput v-model="startDate" type="date" aria-label="开始日期" />
            <span class="date-sep" aria-hidden="true">–</span>
            <AppInput v-model="endDate" type="date" aria-label="结束日期" />
          </div>
        </div>
        <div class="man-cell">
          <span class="man-k">人数</span>
          <div class="person-ctl">
            <button type="button" class="step-btn" aria-label="减少人数" @click="form.persons = Math.max(1, form.persons - 1)">−</button>
            <span class="man-v">{{ form.persons }}</span>
            <button type="button" class="step-btn" aria-label="增加人数" @click="form.persons = Math.min(20, form.persons + 1)">+</button>
          </div>
        </div>
        <div class="man-cell">
          <span class="man-k">天数</span>
          <p class="man-v">{{ form.days }}<span class="man-u">天</span></p>
        </div>
        <div class="man-cell">
          <span class="man-k">预算</span>
          <AppNumberInput v-model="form.budget" :min="0" :step="500" aria-label="预算上限" suffix="元" placeholder="不限" />
        </div>
      </div>
      <div class="quick-row">
        <span class="lp-label">热门</span>
        <button
          v-for="c in quickCities"
          :key="c"
          type="button"
          class="ghost-chip"
          :class="{ active: form.city === c }"
          @click="form.city = c"
        >
          {{ c }}
        </button>
        <button type="button" class="link-btn" @click="guideVisible = true">AI 帮我选</button>
      </div>
    </section>

    <section class="taste">
      <h2 class="section-title">口味与要求</h2>
      <div class="chip-row">
        <button
          v-for="t in PREFERENCE_TAGS"
          :key="t"
          type="button"
          class="ghost-chip"
          :class="{ active: form.preferences.includes(t) }"
          :aria-pressed="form.preferences.includes(t)"
          @click="togglePreference(t)"
        >
          {{ t }}
        </button>
        <span class="taste-div" aria-hidden="true"></span>
        <button
          v-for="t in HOTEL_TIERS"
          :key="t"
          type="button"
          class="ghost-chip"
          :class="{ active: form.hotelTier === t }"
          :aria-pressed="form.hotelTier === t"
          @click="form.hotelTier = form.hotelTier === t ? '' : t"
        >
          {{ t }}
        </button>
      </div>
      <div class="req-block">
        <label class="man-k" for="trip-say">特别要求</label>
        <div class="req-input">
          <AppInput
            id="trip-say"
            v-model="say"
            placeholder="想体验一次慢船下午茶；不吃辣…"
            aria-label="特别要求"
            @enter="onSay"
          />
          <button type="button" class="btn-ghost" @click="onSay">记下</button>
        </div>
        <ul v-if="reqList.length" class="req-list">
          <li v-for="(m, i) in reqList" :key="i">
            <span>{{ m }}</span>
            <button type="button" class="link-btn" @click="reqList.splice(i, 1)">移除</button>
          </li>
        </ul>
      </div>
    </section>

    <p v-if="errorMsg" class="submit-error" role="alert">{{ errorMsg }}</p>
    <VerificationNotice />

    <AppSheet v-model="guideVisible" title="目的地引导">
      <div class="guide-chat">
        <div v-for="(m, i) in guideMsgs" :key="i" class="chat-line" :class="m.role">{{ m.text }}</div>
        <div v-if="guideSugs.length" class="guide-sugs">
          <button v-for="s in guideSugs" :key="s.name" type="button" class="ghost-chip" :title="s.reason" @click="pickSug(s.name)">
            {{ s.name }}
          </button>
        </div>
      </div>
      <div class="req-input">
        <AppInput
          v-model="guideInput"
          placeholder="回复你的偏好…"
          aria-label="目的地引导输入"
          :disabled="guideLoading"
          @enter="onGuideEnter"
        />
        <button type="button" class="btn-ghost" :disabled="guideLoading" @click="sendGuide">发送</button>
      </div>
      <div v-if="guideCity" class="guide-confirm">
        <button type="button" class="btn-primary" @click="confirmGuideCity">去 {{ guideCity }}</button>
      </div>
    </AppSheet>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, onMounted } from 'vue'

import { generateItinerary, cityGuide, newIdempotencyKey } from '../../api'
import AppInput from '../ui/AppInput.vue'
import AppNumberInput from '../ui/AppNumberInput.vue'
import AppSheet from '../ui/AppSheet.vue'
import AppTextarea from '../ui/AppTextarea.vue'
import { confirmDialog } from '../ui/confirm'
import { toast } from '../ui/toast'
import VerificationNotice from './VerificationNotice.vue'
import { fetchSupportedCities, POPULAR_CITIES_FALLBACK } from '../../utils/supportedCities'

const props = defineProps<{ prefillCity?: string }>()
const emit = defineEmits<{ created: [id: string] }>()

const PREFERENCE_TAGS = ['人文历史', '自然风光', '美食', '网红出片', '主题娱乐', '购物']
const HOTEL_TIERS = ['经济型', '舒适型', '高档型', '豪华型', '奢华型']
const QUICK_CITY_LIMIT = 8
const quickCities = ref<string[]>([...POPULAR_CITIES_FALLBACK])
const say = ref('')
const reqList = ref<string[]>([])
const intent = ref('')
const INTENT_MAX = 800
const INTENT_EXAMPLES = ['以自然风光为主，轻松不赶路', '只吃米其林与本地名店', '带父母慢节奏不爬山']
const REQUIREMENTS_MAX = 4000

async function applyIntentExample(text: string) {
  const current = intent.value.trim()
  if (current && current !== text) {
    const ok = await confirmDialog('当前已填写旅行意图，继续将替换为该示例。', {
      title: '覆盖确认',
      confirmText: '覆盖',
      cancelText: '取消',
    })
    if (!ok) return
  }
  intent.value = text
}

const requirements = computed(() => reqList.value.filter(Boolean).join('；'))
const form = reactive({
  city: '',
  days: 2,
  persons: 2,
  budget: null as number | null,
  preferences: [] as string[],
  hotelTier: '',
})
const loading = ref(false)
const errorMsg = ref('')
const startDate = ref('')
const endDate = ref('')
const dateRange = computed<[string, string] | null>(() =>
  startDate.value && endDate.value ? [startDate.value, endDate.value] : null,
)
const generationKey = ref(newIdempotencyKey())

const brief = computed(() => {
  if (!form.city.trim()) return null
  const parts = [`${form.days} 天`, `${form.persons} 人`]
  if (startDate.value && endDate.value) parts.push(`${fmtDate(startDate.value)} – ${fmtDate(endDate.value)}`)
  if (form.budget) parts.push(`预算 ¥${form.budget.toLocaleString()}`)
  return { city: form.city.trim(), summary: parts.join(' · ') }
})

function fmtDate(iso: string): string {
  return iso.slice(5).replace('-', '/')
}

function todayIso(): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d.toISOString().slice(0, 10)
}

watch([startDate, endDate], () => {
  if (!startDate.value || !endDate.value) return
  const ms = new Date(endDate.value).getTime() - new Date(startDate.value).getTime()
  const days = Math.round(ms / 86400000) + 1
  if (days >= 1 && days <= 7) form.days = days
  else if (days > 7) {
    endDate.value = ''
    toast.warning('单次行程最多生成 7 天，请重新选择日期范围')
  }
})

watch(
  () => props.prefillCity,
  (city) => {
    if (city) form.city = city
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    quickCities.value = (await fetchSupportedCities()).slice(0, QUICK_CITY_LIMIT)
  } catch {
    /* 离线兜底 */
  }
})

function togglePreference(label: string) {
  const idx = form.preferences.indexOf(label)
  if (idx >= 0) form.preferences.splice(idx, 1)
  else form.preferences.push(label)
}

async function guideIfUnsupported(): Promise<boolean> {
  const input = form.city.trim()
  if (!input) return false
  try {
    const res = await cityGuide(input, [{ role: 'user', content: input }])
    if (res.data.kind !== 'unclear' && res.data.city && res.data.city !== input) {
      provinceHint.value = input
      form.city = res.data.city
      toast.info(`已为您锁定 ${res.data.city}（${input} 的热门目的地）`)
    } else if (res.data.kind === 'unclear') {
      toast.info(res.data.message || '可以直接生成，开放模式为您安排行程')
    }
  } catch {
    /* 静默继续生成 */
  }
  return false
}

async function sendGuideInput(input: string) {
  guideHistory.push({ role: 'user', content: input })
  guideLoading.value = true
  try {
    const res = await cityGuide(input, guideHistory)
    guideSugs.value = res.data.suggestions || []
    guideCity.value = res.data.city || ''
    const text = res.data.message
    guideMsgs.value.push({ role: 'ai', text })
    guideHistory.push({ role: 'assistant', content: text })
  } finally {
    guideLoading.value = false
  }
}

function onSay() {
  const msg = say.value.trim()
  if (!msg) return
  reqList.value.push(msg)
  say.value = ''
}

const guideVisible = ref(false)
const guideMsgs = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const guideInput = ref('')
const guideLoading = ref(false)
const guideSugs = ref<{ name: string; reason: string }[]>([])
const guideCity = ref('')
const provinceHint = ref('')
let guideHistory: { role: string; content: string }[] = []

function onGuideEnter() {
  void sendGuide()
}

async function sendGuide() {
  const msg = guideInput.value.trim()
  if (!msg || guideLoading.value) return
  const last = guideHistory[guideHistory.length - 1]
  if (last?.role === 'user' && last.content === msg) return
  guideMsgs.value.push({ role: 'user', text: msg })
  guideInput.value = ''
  await sendGuideInput(msg)
}

function pickSug(s: string) {
  guideInput.value = '我想去' + s
  void sendGuide()
}

async function confirmGuideCity() {
  form.city = guideCity.value
  guideVisible.value = false
  toast.success('已选择目的地：' + guideCity.value)
  await submit()
}

async function submit(): Promise<boolean> {
  if (!form.city.trim()) {
    toast.warning('请先填写目的地')
    return false
  }
  if (form.days > 7) {
    toast.warning('单次行程最多生成 7 天')
    return false
  }
  const today = todayIso()
  if (startDate.value && startDate.value < today) {
    toast.warning('出行日期不能早于今天，请重新选择')
    return false
  }
  const blocked = await guideIfUnsupported()
  if (blocked) return false
  let intentPayload = intent.value.trim()
  if (intentPayload.length > INTENT_MAX) {
    intentPayload = intentPayload.slice(0, INTENT_MAX)
    toast.warning(`旅行意图超过 ${INTENT_MAX} 字，已自动裁剪至前 ${INTENT_MAX} 字`)
  }
  let requirementsPayload = requirements.value
  if (requirementsPayload.length > REQUIREMENTS_MAX) {
    requirementsPayload = requirementsPayload.slice(0, REQUIREMENTS_MAX)
    toast.warning(`额外要求合计超过 ${REQUIREMENTS_MAX} 字，已自动裁剪`)
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await generateItinerary(
      {
        city: form.city,
        days: form.days,
        persons: form.persons,
        stayNights: Math.max(form.days - 1, 0),
        budget: form.budget ?? undefined,
        startDate: dateRange.value?.[0],
        endDate: dateRange.value?.[1],
        preferences: form.preferences,
        hotelTier: form.hotelTier || undefined,
        regionHint: provinceHint.value || undefined,
        intent: intentPayload || undefined,
        requirements: requirementsPayload || undefined,
      },
      { idempotencyKey: generationKey.value },
    )
    generationKey.value = newIdempotencyKey()
    emit('created', String(res.data.id))
    return true
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : '生成失败'
    return false
  } finally {
    loading.value = false
  }
}

defineExpose({ brief, submit, loading })
</script>

<style scoped>
.create-trip {
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-height: min(72vh, 680px);
  overflow-y: auto;
  padding-right: 4px;
}

.section-title {
  margin: 0 0 14px;
  font-family: var(--lp-font-display);
  font-size: var(--lp-text-section);
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--lp-text-1);
}

.field-label,
.man-k {
  display: block;
  margin-bottom: 6px;
  font-size: var(--lp-text-caption);
  font-weight: 500;
  color: var(--lp-text-muted);
}

.intent-write :deep(textarea) {
  min-height: 88px;
  border: none;
  border-bottom: 1px solid var(--lp-edge-1);
  border-radius: 0;
  box-shadow: none;
  background: transparent;
  padding: 4px 0 12px;
  font-family: var(--lp-font-display);
  font-size: 18px;
  line-height: 1.5;
  letter-spacing: -0.01em;
  color: var(--lp-text-1);
  resize: vertical;
}

.intent-write :deep(textarea:focus) {
  outline: none;
  border-color: var(--lp-edge-1);
  border-bottom-color: var(--lp-accent);
  box-shadow: none;
}

.intent-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.intent-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.intent-counter {
  margin-left: auto;
  font-size: var(--lp-text-micro);
  color: var(--lp-text-faint);
  font-variant-numeric: tabular-nums;
}

.intent-counter.over {
  color: var(--lp-danger);
  font-weight: 600;
}

.manifest-grid {
  display: grid;
  grid-template-columns: 1.2fr 1.5fr 0.7fr 0.6fr 1fr;
  gap: 0;
  border-top: 1px solid var(--lp-edge-1);
  border-bottom: 1px solid var(--lp-edge-1);
}

@media (max-width: 860px) {
  .manifest-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.man-cell {
  padding: 14px 12px 14px 0;
  min-width: 0;
}

.man-cell + .man-cell {
  padding-left: 12px;
  border-left: 1px solid var(--lp-edge-faint);
}

.date-pair {
  display: flex;
  align-items: center;
  gap: 6px;
}

.date-sep {
  color: var(--lp-text-faint);
}

.person-ctl {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--lp-edge-1);
  border-radius: 50%;
  background: var(--lp-surface-card);
  color: var(--lp-text-2);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}

.step-btn:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
}

.man-v {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1;
  color: var(--lp-text-1);
  font-variant-numeric: tabular-nums;
}

.man-u {
  margin-left: 4px;
  font-family: var(--lp-font-ui);
  font-size: 13px;
  font-weight: 500;
  color: var(--lp-text-muted);
}

.quick-row,
.chip-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.taste-div {
  width: 1px;
  height: 18px;
  margin: 0 6px;
  background: var(--lp-edge-1);
}

.req-block {
  margin-top: 18px;
}

.req-input {
  display: flex;
  gap: 8px;
  align-items: center;
}

.req-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.req-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--lp-edge-faint);
  color: var(--lp-text-2);
  font-size: 14px;
}

.submit-error {
  margin: 0;
  color: var(--lp-danger);
  font-size: 13px;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 16px;
  border: none;
  border-radius: var(--lp-radius-sm);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-ghost {
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-sm);
  background: transparent;
  color: var(--lp-text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.ghost-chip {
  min-height: 32px;
  padding: 5px 12px;
  border: 1px solid transparent;
  border-radius: var(--lp-radius-pill);
  background: var(--lp-surface-2);
  color: var(--lp-text-2);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.ghost-chip.active {
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}

.link-btn {
  border: none;
  background: none;
  padding: 0;
  color: var(--lp-accent);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.guide-chat {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.chat-line {
  padding: 8px 12px;
  border-radius: var(--lp-radius-sm);
  font-size: 14px;
  line-height: 1.5;
}

.chat-line.user {
  background: var(--lp-accent-subtle);
  color: var(--lp-text-1);
  align-self: flex-end;
  max-width: 90%;
}

.chat-line.ai {
  background: var(--lp-surface-2);
  color: var(--lp-text-2);
  align-self: flex-start;
  max-width: 90%;
}

.guide-sugs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.guide-confirm {
  margin-top: 16px;
}
</style>
