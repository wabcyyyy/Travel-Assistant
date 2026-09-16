<template>
  <div class="generate-page">
    <div class="lp-page-head stack">
      <span class="bar"></span>
      <h2>行程生成</h2>
      <span class="sub">先写清旅行意图，其余交给 Agent</span>
    </div>

    <!-- 约稿单：意图是唯一主角（全宽置顶），下方两栏行内字段，底部约稿汇总 + 开始生成 -->
    <div class="gen-stack">
        <!-- 旅行意图：最高优先级生成信号 -->
        <el-card shadow="never" class="group-card intent-card">
      <template #header>
        <div class="group-head">
          <span class="group-title">旅行意图</span>
          <span class="group-badge">最高优先级信号</span>
        </div>
      </template>
      <div class="intent-block">
        <div class="intent-shell">
          <el-input
            v-model="intent"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
            resize="none"
            placeholder="一句话说清这趟旅行最想要什么，例如：成都 4 日，以美食和市井街区为主，节奏松弛"
          />
        </div>
        <!-- 右下角实时计数：超限红字提示但不阻断输入，提交时裁剪 -->
        <div class="intent-counter" :class="{ over: intent.length > INTENT_MAX }">
          {{ intent.length }}/{{ INTENT_MAX }}
        </div>
        <div class="intent-examples">
          <span class="hint">示例</span>
          <button
            v-for="e in INTENT_EXAMPLES"
            :key="e"
            type="button"
            class="intent-chip"
            @click="applyIntentExample(e)"
          >
            {{ e }}
          </button>
        </div>
        <span class="hint intent-note">意图是生成的最高优先级信号；下方偏好标签作为辅助信号</span>
      </div>
        </el-card>

    <!-- 两栏：左行程要素 / 右口味与要求 -->
    <div class="gen-columns">
      <el-card shadow="never" class="group-card">
      <template #header>
        <span class="group-title">行程要素</span>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        style="max-width: 100%"
      >
        <el-row :gutter="16">
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
        <el-row :gutter="16">
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
              <el-input-number v-model="form.days" :min="1" :max="7" disabled style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="预算上限">
              <el-input-number v-model="form.budget" :min="0" :step="500" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="form-tips">
          <span class="hint">天数由所选日期自动计算（含头含尾，最多 7 天）</span>
          <el-button link type="primary" @click="guideVisible = !guideVisible">拿不准去哪？AI 帮我选</el-button>
        </div>
        <div class="quick-cities">
          <span class="hint">热门目的地</span>
          <button
            v-for="c in POPULAR_CITIES"
            :key="c"
            type="button"
            class="city-chip"
            :class="{ active: form.city === c }"
            @click="form.city = c"
          >
            {{ c }}
          </button>
        </div>
      </el-form>
    </el-card>

      <!-- 右栏：口味与要求（偏好标签 + 住宿档次 + 特别要求输入） -->
      <el-card shadow="never" class="group-card">
      <template #header>
        <span class="group-title">口味与要求</span>
      </template>
      <el-form label-width="100px" style="max-width: none">
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
              <el-icon :size="18"><component :is="t.icon" /></el-icon>
              {{ t.label }}
            </button>
          </div>
          <span class="hint pref-note">标签帮系统快速定向；具体想要什么，请写在上方意图里</span>
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
      <el-divider />
      <p class="side-sub">特别要求</p>
      <p class="chat-tip">有特别安排？直接输入（如「想吃地道的本地小吃」「想看一场川剧变脸」），生成行程时 AI 会纳入规划；多条要求合计不超过 4000 字。</p>
      <div v-for="(m, i) in chat" :key="i" class="chat-line" :class="m.role">
        {{ m.text }}
      </div>
      <div class="chat-input">
        <el-input
          v-model="say"
          placeholder="例如：想体验一次慢船下午茶；不吃辣"
          @keydown.enter="onSayEnter"
        />
        <el-button type="primary" plain @click="onSay">发送</el-button>
      </div>
      </el-card>
    </div>

    <!-- 约稿汇总 + 开始生成 -->
    <el-card shadow="never" class="group-card submit-card">
      <div class="trip-brief">
        <template v-if="form.city">
          <span class="brief-city">{{ form.city }}</span>
          <span class="brief-meta">{{ form.days }} 天行程</span>
          <span v-if="dateRange?.[0] && dateRange?.[1]" class="brief-meta">{{ dateRange[0].slice(5).replace('-', '/') }} - {{ dateRange[1].slice(5).replace('-', '/') }}</span>
          <span class="brief-meta">{{ form.persons }} 人出行</span>
          <span v-if="form.budget" class="brief-meta">预算 ¥{{ form.budget.toLocaleString() }}</span>
          <span v-if="form.hotelTier" class="brief-meta">{{ form.hotelTier }}</span>
        </template>
        <span v-else class="brief-empty">选定目的地后，这里会实时汇总你的行程安排</span>
      </div>
      <div class="submit-row">
        <el-alert
          v-if="errorMsg"
          :title="errorMsg"
          type="error"
          :closable="false"
          show-icon
          class="submit-error"
        />
        <el-button type="primary" size="large" class="submit" :loading="loading" @click="onSubmit">
          开始生成
        </el-button>
      </div>
    </el-card>
    </div>

    <!-- 城市引导侧边抽屉 -->
    <el-drawer v-model="guideVisible" title="目的地引导" size="min(380px, 92vw)" append-to-body>
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
import { reactive, ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
// ElMessage/ElMessageBox 由 AutoImport resolver 按需注入（含样式）；表单类型仍显式声明
import type { FormInstance, FormRules } from 'element-plus'
import {
  Camera,
  Food,
  MagicStick,
  Reading,
  ShoppingBag,
  Sunny,
} from '@element-plus/icons-vue'

import { generateItinerary, cityGuide, newIdempotencyKey } from '../api'

const router = useRouter()
const route = useRoute()
const formRef = ref<FormInstance>()


const PREFERENCE_TAGS = [
  { label: '人文历史', icon: Reading },
  { label: '自然风光', icon: Sunny },
  { label: '美食', icon: Food },
  { label: '网红出片', icon: Camera },
  { label: '主题娱乐', icon: MagicStick },
  { label: '购物', icon: ShoppingBag },
]

const HOTEL_TIERS = ['经济型', '舒适型', '高档型', '豪华型', '奢华型']

// 热门目的地快捷选择（点击直接填入目的地）
const POPULAR_CITIES = ['成都', '杭州', '西安', '重庆', '北京', '上海']

const chat = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const say = ref('')

// 旅行意图（§5.2 完整版）：置顶 00 主输入区块，最高优先级生成信号透传给 Agent；
// 超限不阻断输入，提交时裁剪至 800 字并提示
const intent = ref('')
const INTENT_MAX = 800
const INTENT_EXAMPLES = [
  '以自然风光为主，轻松不赶路',
  '只吃米其林与本地名店',
  '带父母慢节奏不爬山',
]

// 额外要求合计上限 4000 字，同样提交时裁剪
const REQUIREMENTS_MAX = 4000

// 意图示例 chip：点击填入并替换；已有内容时先轻提示确认再覆盖
async function applyIntentExample(text: string) {
  const current = intent.value.trim()
  if (current && current !== text) {
    try {
      await ElMessageBox.confirm('当前已填写旅行意图，继续将替换为该示例。', '覆盖确认', {
        type: 'warning',
        confirmButtonText: '覆盖',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  intent.value = text
}

// 汇总用户输入的全部额外要求，生成行程时随请求发送给 Agent
const requirements = computed(() =>
  chat.value.filter((m) => m.role === 'user').map((m) => m.text.trim()).filter(Boolean).join('；'),
)

const form = reactive({
  city: '',
  days: 2,
  persons: 2,
  budget: null as number | null,
  preferences: [] as string[],
  hotelTier: '' as string,
})

const loading = ref(false)
const errorMsg = ref('')
const dateRange = ref<[string, string] | null>(null)
/**
 * 幂等键：进入页面生成一次，本次流程内的失败重试（再点生成）复用同一个键——
 * 网络超时时服务端可能已建壳，复用键让后端回放同一个行程而不是建第二份
 * （防双击 / 弱网重复提交造成重复 LLM 账单）。成功后跳转离开页面，键随之作废。
 */
const generationKey = ref(newIdempotencyKey())

function disablePastDate(date: Date) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}

// 天数由所选日期区间自动计算（含头含尾），住宿晚数恒为天数 - 1
watch(dateRange, (range) => {
  if (!range || !range[0] || !range[1]) return
  const ms = new Date(range[1]).getTime() - new Date(range[0]).getTime()
  const days = Math.round(ms / 86400000) + 1
  if (days >= 1 && days <= 7) {
    form.days = days
  } else if (days > 7) {
    dateRange.value = null
    ElMessage.warning('单次行程最多生成 7 天，请重新选择日期范围')
  }
})

onMounted(() => {
  // 首页目的地墙点击跳转：/generate?city=杭州
  const cityFromQuery = typeof route.query.city === 'string' ? route.query.city.trim() : ''
  if (cityFromQuery && !form.city) {
    form.city = cityFromQuery
  }
  // 偏好标签不回填历史偏好：每次进入约稿单都从空白开始，由用户当次勾选
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

// EP 按需后 el-input keydown 事件签名为 Event | KeyboardEvent，用类型守卫窄化判 IME 组合输入
function onSayEnter(e: Event | KeyboardEvent) {
  if ('isComposing' in e && e.isComposing) return
  onSay()
}

// 额外要求为纯输入模式：不做 LLM 对话解析，仅记录内容，
// 固定回复「收到」表示已记录，生成行程时随请求发送给 Agent。
function onSay() {
  const msg = say.value.trim()
  if (!msg) return
  chat.value.push({ role: 'user', text: msg })
  say.value = ''
  chat.value.push({ role: 'ai', text: '收到！生成行程时会考虑这条要求' })
}

const guideVisible = ref(false)
const guideMsgs = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const guideInput = ref('')
const guideLoading = ref(false)
const guideSugs = ref<{ name: string; reason: string }[]>([])
const guideCity = ref('')
const provinceHint = ref('')
let guideHistory: { role: string; content: string }[] = []

function onGuideEnter(e: Event | KeyboardEvent) {
  if ('isComposing' in e && e.isComposing) return
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
  days: [{ required: true, message: '请选择出行日期', trigger: 'change' }],
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
  // 意图超限不阻断输入：提交时裁剪至 800 字并提示
  let intentPayload = intent.value.trim()
  if (intentPayload.length > INTENT_MAX) {
    intentPayload = intentPayload.slice(0, INTENT_MAX)
    ElMessage.warning(`旅行意图超过 ${INTENT_MAX} 字，已自动裁剪至前 ${INTENT_MAX} 字`)
  }
  // 额外要求合计超 4000 字时同样提交时裁剪
  let requirementsPayload = requirements.value
  if (requirementsPayload.length > REQUIREMENTS_MAX) {
    requirementsPayload = requirementsPayload.slice(0, REQUIREMENTS_MAX)
    ElMessage.warning(`额外要求合计超过 ${REQUIREMENTS_MAX} 字，已自动裁剪`)
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await generateItinerary(
      {
        city: form.city,
        days: form.days,
        persons: form.persons,
        stayNights: Math.max(form.days - 1, 0), // 后端契约保留，由天数派生
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
    generationKey.value = newIdempotencyKey() // 成功即流程结束；回退再生成是新流程
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
  max-width: var(--lp-content, 1120px);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 表单标签视觉字重 */
:deep(.el-form-item__label) {
  font-weight: 600;
}

/* 热门目的地快捷芯片：药丸形，hover 轻浮起 */
.quick-cities {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0 0;
  padding-left: 0;
}

/* ---------- 00 旅行意图：★ 主输入（§5.2） ---------- */
.intent-block {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 意图输入壳：常态细灰描边，聚焦时转 --lp-theme-accent 渐变描边（padding 技法做渐变环） */
.intent-shell {
  padding: 1.5px;
  border-radius: 10px;
  background: var(--lp-border);
  transition:
    background 0.2s ease,
    box-shadow 0.2s ease;
}

.intent-shell:focus-within {
  background: var(--lp-theme-accent);
  box-shadow: 0 0 0 3px var(--lp-accent-soft);
}

/* 内层 textarea 去掉默认描边环，交由外壳统一表达聚焦态 */
.intent-shell :deep(.el-textarea__inner),
.intent-shell :deep(.el-textarea__inner:focus) {
  border-radius: 8.5px;
  border: none;
  box-shadow: none;
  font-size: 15px;
  line-height: 1.7;
  background: var(--lp-surface);
}

/* 右下角实时计数器：超限红字，不阻断输入 */
.intent-counter {
  align-self: flex-end;
  margin-top: -2px;
  font-size: 11px;
  color: var(--lp-muted);
  font-variant-numeric: tabular-nums;
}

.intent-counter.over {
  color: var(--lp-danger);
  font-weight: 600;
}

.intent-examples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

/* 意图示例 chip：--lp-accent 描边药丸，与 02 弱化实底标签形成主次 */
.intent-chip {
  min-height: 32px;
  padding: 5px 14px;
  border: 1px solid var(--lp-accent);
  border-radius: 999px;
  background: var(--lp-surface);
  color: var(--lp-accent);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease,
    transform 0.15s ease;
}

.intent-chip:hover {
  background: var(--lp-accent-soft);
  color: var(--lp-accent-hover);
  transform: translateY(-1px);
}

.intent-chip:active {
  transform: translateY(0) scale(0.98);
}

.intent-chip:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.intent-note {
  white-space: normal;
}

.city-chip {
  min-height: 36px;
  padding: 6px 16px;
  border: 1px solid var(--lp-border);
  border-radius: 999px;
  background: #fff;
  color: var(--lp-ink-soft);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.city-chip:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent);
  transform: translateY(-1px);
}

.city-chip:active {
  transform: translateY(0) scale(0.98);
}

.city-chip.active {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: #fff;
  font-weight: 600;
  box-shadow: var(--lp-shadow-accent);
}

.city-chip:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

/* 生成前行程速览条：强调色左缘 + 基线排版，主次分明 */
.trip-brief {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-bottom: 14px;
  padding: 13px 16px;
  background: var(--lp-accent-soft);
  border-left: 3px solid var(--lp-accent);
  border-radius: 12px;
}

.brief-city {
  font-size: 17px;
  font-weight: 800;
  color: var(--lp-ink);
  letter-spacing: -0.01em;
}

.brief-meta {
  color: var(--lp-ink-soft);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.brief-empty {
  color: var(--lp-muted);
  font-size: 13px;
}

.form-tips {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin: 2px 0 0;
}

.form-tips .hint {
  white-space: nowrap;
}

/* 卡片头：标题 + 角标（★ 主输入 / ◇ 辅助信号 / ◇ 硬约束） */
.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.group-title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: var(--lp-font-display);
  font-weight: 600;
  font-size: 18px;
  color: var(--lp-ink);
  letter-spacing: 0.01em;
}

.group-badge {
  flex: none;
  padding: 2px 10px;
  border: 1px dashed var(--lp-border);
  border-radius: 999px;
  color: var(--lp-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.hint {
  color: var(--lp-muted);
  font-size: 13px;
  white-space: nowrap;
}

/* ---------- 约稿单堆叠：意图 → 两栏要素/口味 → 汇总付印 ---------- */
.gen-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 两栏行内字段：左行程要素 / 右口味与要求；窄屏折叠单列 */
.gen-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 900px) {
  .gen-columns {
    grid-template-columns: 1fr;
  }
}

/* 右栏「特别要求」小节标题 */
.side-sub {
  margin: 0 0 8px;
  font-weight: 700;
  font-size: 13px;
  color: var(--lp-ink);
}

/* 汇总提交卡：铺满宽度，按钮靠右 */
.submit-card .submit-row {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
}

.submit-card .submit-error {
  flex: 1;
}

/* ---------- 偏好标签（◇ 辅助信号：缩小一号 + 降饱和弱化） ---------- */
.tag-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.pref-note {
  width: 100%;
  margin-top: 2px;
  white-space: normal;
}

.pref-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 5px 13px;
  border: 1px solid var(--lp-rule);
  border-radius: 999px;
  background: var(--lp-surface);
  color: var(--lp-muted);
  font-size: 13px;
  cursor: pointer;
  transition:
    background 0.15s ease,
    color 0.15s ease,
    border-color 0.15s ease,
    transform 0.15s ease,
    box-shadow 0.15s ease;
}

.pref-tag:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent-hover);
  transform: translateY(-1px);
}

.pref-tag:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.pref-tag.active {
  background: var(--lp-accent);
  border-color: var(--lp-accent);
  color: #fff;
  box-shadow: var(--lp-shadow-accent);
}

.pref-tag .el-icon {
  font-size: 13px;
  color: inherit;
}

.chat-tip {
  margin: 0 0 10px;
  color: var(--lp-muted);
  font-size: 13px;
}

/* chat 行：与 theme.css 公共层同名类去重后，仅保留本页差异两值
   （padding/max-width 与公共基线不同；圆角/字号/配色复用公共层，渲染不变） */
.chat-line {
  padding: 6px 12px;
  max-width: 80%;
}

.chat-input {
  display: flex;
  gap: 8px;
  margin-top: 4px;
  max-width: 680px;
}

/* 提交区：主按钮全宽「开始规划」，错误提示在其上方 */
.submit-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.submit-error {
  width: 100%;
}

.submit {
  width: 100%;
  font-weight: 700;
  letter-spacing: 0.08em;
  box-shadow: var(--lp-shadow-accent);
}

.guide-sugs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0;
}

.guide-sug {
  min-height: 36px;
  padding: 6px 14px;
  border: 1px solid var(--lp-border);
  border-radius: 999px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  transition:
    border-color 0.15s ease,
    color 0.15s ease;
}

.guide-sug:hover {
  border-color: var(--lp-accent);
  color: var(--lp-accent-hover);
}

.guide-confirm {
  margin-top: 14px;
}

.guide-chat {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

@media (max-width: 720px) {
  :deep(.el-form-item__label) {
    width: 100% !important;
    justify-content: flex-start;
  }

  :deep(.el-form-item__content) {
    margin-left: 0 !important;
  }

  .trip-brief {
    border-radius: 10px;
  }
}
</style>
