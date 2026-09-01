<template>
  <div class="generate-page" :style="{ transform: guideVisible ? 'translateX(-100px)' : 'none' }">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>行程生成</h2>
      <span class="sub">填写基本信息，其余交给 Agent</span>
    </div>

    <!-- 第一栏：目的地与出行 -->
    <el-card shadow="never" class="group-card">
      <template #header>
        <span class="group-title">目的地与出行</span>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        style="max-width: 100%"
      >
        <el-row :gutter="12">
          <el-col :span="14">
            <el-form-item label="目的地" prop="city">
              <el-input v-model="form.city" placeholder="城市或省份" />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="人数" prop="persons">
              <el-input-number v-model="form.persons" :min="1" :max="20" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="14">
            <el-form-item label="出行日期">
              <el-date-picker
                v-model="dateRange"
                type="daterange"
                value-format="YYYY-MM-DD"
                :disabled-date="disablePastDate"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="天数" prop="days">
              <el-input-number v-model="form.days" :min="1" :max="7" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="9">
            <el-form-item label="住宿晚数" prop="stayNights">
              <el-input-number v-model="form.stayNights" :min="0" :max="form.days" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="15">
            <el-form-item label="预算上限">
              <el-input-number v-model="form.budget" :min="0" :step="500" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="form-tips">
          <span class="hint">天数随日期自动计算；住宿默认少 1 晚</span>
          <el-button link type="primary" @click="guideVisible = !guideVisible">🧭 拿不准去哪？AI 帮我选</el-button>
        </div>
      </el-form>
    </el-card>

    <!-- 第二栏：偏好设置 -->
    <el-card shadow="never" class="group-card">
      <template #header>
        <span class="group-title">偏好设置</span>
      </template>
      <el-form label-width="100px" style="max-width: 720px">
        <el-form-item label="旅行偏好">
          <div class="tag-grid">
            <button
              v-for="t in PREFERENCE_TAGS"
              :key="t.label"
              type="button"
              class="pref-tag"
              :class="{ active: form.preferences.includes(t.label) }"
              @click="togglePreference(t.label)"
            >
              <Icon :icon="t.icon" width="20" />
              {{ t.label }}
            </button>
          </div>
        </el-form-item>
        <el-form-item label="住宿偏好">
          <el-select
            v-model="form.hotelTier"
            clearable
            placeholder="不限（默认按舒适档推荐）"
            style="width: 100%"
          >
            <el-option v-for="t in HOTEL_TIERS" :key="t" :label="t" :value="t" />
          </el-select>
          <span class="hint">选择一个主要档次；不选则由 Agent 推荐</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 第三栏：额外要求 + 生成按钮 -->
    <el-card shadow="never" class="chat-card">
      <template #header>
        <span class="group-title">额外要求</span>
      </template>
      <p class="chat-tip">有特别安排？用一句话告诉我们，AI 会帮你补全或调整上面的表单。</p>
      <div v-for="(m, i) in chat" :key="i" class="chat-line" :class="m.role">
        {{ m.text }}
      </div>
      <div class="chat-input">
        <el-input
          v-model="say"
          placeholder="例如：想去杭州玩 3 天，2 个人，10 月 1 日出发"
          @keydown.enter="onSayEnter"
        />
        <el-button type="primary" plain :loading="thinking" @click="onSay">发送</el-button>
      </div>

      <el-divider />
      <div class="submit-row">
        <el-button type="primary" size="large" class="submit" :loading="loading" @click="onSubmit">
          生成行程
        </el-button>
      </div>
      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        :closable="false"
        show-icon
      />
    </el-card>

    <!-- 城市引导侧边抽屉 -->
    <el-drawer v-model="guideVisible" title="🧭 目的地引导" size="380px" :modal="false" append-to-body>
      <div class="guide-chat">
        <div v-for="(m, i) in guideMsgs" :key="i" class="chat-line" :class="m.role">{{ m.text }}</div>
        <div v-if="guideSugs.length" class="guide-sugs">
          <button v-for="s in guideSugs" :key="s.name" type="button" class="guide-sug" :title="s.reason" @click="pickSug(s.name)">{{ s.name }}</button>
        </div>
      </div>
      <div class="chat-input" style="margin-top: 12px">
        <el-input v-model="guideInput" placeholder="回复你的偏好…" @keydown.enter="onGuideEnter" />
        <el-button type="primary" :loading="guideLoading" @click="sendGuide">发送</el-button>
      </div>
      <div v-if="guideCity" class="guide-confirm">
        <el-button type="primary" style="width: 100%" @click="confirmGuideCity">去 {{ guideCity }}</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Icon } from '@iconify/vue'

import { generateItinerary, clarifyTrip, cityGuide, getTopPreferences } from '../api'

const router = useRouter()
const formRef = ref<FormInstance>()


const PREFERENCE_TAGS = [
  { label: '人文历史', icon: 'fluent-emoji:classical-building' },
  { label: '自然风光', icon: 'fluent-emoji:national-park' },
  { label: '美食', icon: 'fluent-emoji:fork-and-knife-with-plate' },
  { label: '网红出片', icon: 'fluent-emoji:camera-with-flash' },
  { label: '主题娱乐', icon: 'fluent-emoji:ferris-wheel' },
  { label: '购物', icon: 'fluent-emoji:shopping-bags' },
]

const HOTEL_TIERS = ['经济型', '舒适型', '高档型', '豪华型', '奢华型']

const chat = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const say = ref('')
const thinking = ref(false)

const form = reactive({
  city: '',
  days: 2,
  persons: 2,
  stayNights: 1,
  budget: null as number | null,
  preferences: [] as string[],
  hotelTier: '' as string,
})

const loading = ref(false)
const errorMsg = ref('')
const dateRange = ref<[string, string] | null>(null)

const CLARIFY_SLOTS_KEY = 'travel_clarify_slots'
function loadClarifySlots(): Record<string, unknown> {
  try {
    const saved = localStorage.getItem(CLARIFY_SLOTS_KEY)
    return saved ? JSON.parse(saved) : {}
  } catch { return {} }
}

const clarifySlots = ref<Record<string, unknown>>(loadClarifySlots())

function disablePastDate(date: Date) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}

// 出行天数由所选日期区间自动计算（含头含尾）；未选日期时可手填
watch(dateRange, (range) => {
  if (!range || !range[0] || !range[1]) return
  const ms = new Date(range[1]).getTime() - new Date(range[0]).getTime()
  const days = Math.round(ms / 86400000) + 1
  if (days >= 1 && days <= 7) {
    form.days = days
    form.stayNights = Math.max(days - 1, 0)
  } else if (days > 7) {
    dateRange.value = null
    ElMessage.warning('单次行程最多生成 7 天，请重新选择日期范围')
  }
})

watch(() => form.days, (days, previousDays) => {
  if (form.stayNights === Math.max(previousDays - 1, 0) || form.stayNights > days) {
    form.stayNights = Math.max(days - 1, 0)
  }
})

onMounted(async () => {
  try {
    const res = await getTopPreferences({ skipErrorMessage: true })
    if (res.data?.length && form.preferences.length === 0) {
      form.preferences = res.data
    }
  } catch { /* 静默，首次无历史偏好时忽略 */ }
})

function togglePreference(label: string) {
  const idx = form.preferences.indexOf(label)
  if (idx >= 0) {
    form.preferences.splice(idx, 1)
  } else {
    form.preferences.push(label)
  }
}

async function guideIfUnsupported(): Promise<boolean> {
  const input = form.city.trim()
  if (!input) return false
  try {
    const res = await cityGuide(input, [{ role: 'user', content: input }])
    if (res.data.kind !== 'unclear' && res.data.city && res.data.city !== input) {
      provinceHint.value = input
      form.city = res.data.city
      ElMessage.info(`已为您锁定 ${res.data.city}（${input} 的热门目的地）`)
    } else if (res.data.kind === 'unclear') {
      ElMessage.info(res.data.message || '可以直接生成，开放模式为您安排行程')
    }
  } catch { /* 静默继续生成，后端开放模式兜底 */ }
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

function onSayEnter(e: KeyboardEvent) {
  if ((e as any).isComposing) return
  onSay()
}

async function onSay() {
  const msg = say.value.trim()
  if (!msg || thinking.value) return
  chat.value.push({ role: 'user', text: msg })
  say.value = ''
  thinking.value = true
  try {
    const res = await clarifyTrip({ message: msg, slots: clarifySlots.value })
    clarifySlots.value = res.data.slots || {}
    localStorage.setItem(CLARIFY_SLOTS_KEY, JSON.stringify(clarifySlots.value))
    applySlots(res.data.slots || {})
    chat.value.push({
      role: 'ai',
      text: res.data.ready ? '信息齐了！点击「生成行程」即可 ✅' : res.data.question || '还有信息需要补充',
    })
  } catch {
    chat.value.push({ role: 'ai', text: '没太理解，换个说法试试？' })
  } finally {
    thinking.value = false
  }
}

function applySlots(slots: Record<string, unknown>) {
  if (slots.city) form.city = String(slots.city)
  if (slots.days) form.days = Number(slots.days)
  if (slots.stay_nights != null) form.stayNights = Number(slots.stay_nights)
  if (slots.persons) form.persons = Number(slots.persons)
  if (slots.budget != null) form.budget = Number(slots.budget)
  if (slots.hotel_tier) form.hotelTier = String(slots.hotel_tier)
  if (Array.isArray(slots.preferences)) {
    form.preferences = slots.preferences.map(String).filter((value) => PREFERENCE_TAGS.some((tag) => tag.label === value))
  }
  if (slots.start_date) {
    const s = String(slots.start_date)
    const d = new Date(s)
    d.setDate(d.getDate() + Number(slots.days || form.days) - 1)
    const pad = (n: number) => String(n).padStart(2, '0')
    dateRange.value = [s, `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`]
  }
}

const guideVisible = ref(false)
const guideMsgs = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const guideInput = ref('')
const guideLoading = ref(false)
const guideSugs = ref<{ name: string; reason: string }[]>([])
const guideCity = ref('')
const provinceHint = ref('')
let guideHistory: { role: string; content: string }[] = []

function onGuideEnter(e: KeyboardEvent) {
  if ((e as any).isComposing) return
  sendGuide()
}

async function sendGuide() {
  const msg = guideInput.value.trim()
  if (!msg || guideLoading.value) return
  const last = guideHistory[guideHistory.length - 1]
  if (last?.role === 'user' && last.content === msg) return // 防连击重复
  guideMsgs.value.push({ role: 'user', text: msg })
  guideInput.value = ''
  await sendGuideInput(msg)
}

function pickSug(s: string) {
  guideInput.value = '我想去' + s
  sendGuide()
}

async function confirmGuideCity() {
  form.city = guideCity.value
  guideVisible.value = false
  ElMessage.success('已选择目的地：' + guideCity.value + '，开始生成…')
  await onSubmit()
}

const rules: FormRules = {
  city: [{ required: true, message: '请输入目的地', trigger: 'blur' }],
  days: [{ required: true, message: '请输入出行天数', trigger: 'change' }],
  stayNights: [{ required: true, message: '请输入住宿晚数', trigger: 'change' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (form.days > 7) {
    ElMessage.warning('单次行程最多生成 7 天')
    return
  }
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  if (dateRange.value?.[0] && new Date(dateRange.value[0]).getTime() < today.getTime()) {
    ElMessage.warning('出行日期不能早于今天，请重新选择')
    return
  }
  const blocked = await guideIfUnsupported()
  if (blocked) return
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await generateItinerary({
      city: form.city,
      days: form.days,
      persons: form.persons,
      stayNights: form.stayNights,
      budget: form.budget ?? undefined,
      startDate: dateRange.value?.[0],
      endDate: dateRange.value?.[1],
      preferences: form.preferences,
      hotelTier: form.hotelTier || undefined,
      regionHint: provinceHint.value || undefined,
    })
    localStorage.removeItem(CLARIFY_SLOTS_KEY)
    router.push({ name: 'trip-detail', params: { id: res.data.id } })
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : '生成失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.generate-page {
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  transition: transform 0.3s ease;
}

.form-tips {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -6px 0 0 90px;
}

.group-title {
  font-weight: 800;
  letter-spacing: 0.04em;
}

.hint {
  margin-left: 10px;
  color: var(--lp-muted);
  font-size: 12px;
}

/* ---------- 偏好标签 ---------- */
.tag-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.pref-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: 1px solid var(--lp-border);
  border-radius: 999px;
  background: var(--lp-surface);
  color: var(--lp-ink-soft);
  font-size: 14px;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
}

.pref-tag:hover {
  border-color: var(--lp-ink);
}

.pref-tag.active {
  background: var(--lp-ink);
  border-color: var(--lp-ink);
  color: #fff;
}

.pref-tag .el-icon {
  font-size: 15px;
}

.chat-tip {
  margin: 0 0 10px;
  color: var(--lp-muted);
  font-size: 13px;
}

.chat-line {
  padding: 6px 12px;
  border-radius: 10px;
  margin-bottom: 8px;
  max-width: 80%;
  font-size: 14px;
}

.chat-line.user {
  background: var(--lp-ink);
  color: #fff;
  margin-left: auto;
  width: fit-content;
}

.chat-line.ai {
  background: var(--lp-sand);
  color: var(--lp-ink);
  width: fit-content;
}

.chat-input {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.submit-row {
  display: flex;
  justify-content: center;
}

.guide-sugs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0;
}

.guide-sug {
  padding: 6px 14px;
  border: 1px solid var(--lp-border);
  border-radius: 999px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
}

.guide-sug:hover {
  border-color: var(--lp-ink);
}

.guide-confirm {
  margin-top: 14px;
}

.guide-chat {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.submit {
  min-width: 220px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
</style>
