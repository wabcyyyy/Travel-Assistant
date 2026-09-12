<template>
  <div class="nl-edit">
    <button
      type="button"
      class="nl-toggle"
      :aria-expanded="nlOpen ? 'true' : 'false'"
      @click="nlOpen = !nlOpen"
    >
      <span>{{ nlOpen ? '收起智能修改' : '智能修改行程' }}</span>
      <span class="nl-toggle-hint">
        {{ chatMsgs.length ? `${chatMsgs.length} 条对话` : '用一句话调整酒店、节奏或点位' }}
      </span>
    </button>
    <div v-show="nlOpen" class="nl-panel">
      <!-- a11y §5.5 #3：role=log 语义化聊天记录；aria-live=polite 播报新增消息，
           流式打字中的占位消息置 aria-busy 避免逐 token 反复播报（历史消息不回放） -->
      <ul class="chat-scroll" role="log" aria-live="polite" aria-label="智能修改对话记录">
        <li
          v-for="(m, i) in chatMsgs"
          :key="m.id || i"
          class="chat-line"
          :class="m.role"
          :aria-label="m.role === 'ai' ? '助手回复' : '我发送的消息'"
          :aria-busy="isStreaming(m) ? 'true' : undefined"
        >
          <div v-if="m.role === 'ai'" class="markdown-body" v-html="renderMarkdown(m.content)"></div>
          <template v-else>{{ m.content }}</template>
          <div v-if="m.plans && m.plans.length" class="draft-preview">
            <div class="draft-summary-title">本次变更</div>
            <div v-for="change in draftChanges(m)" :key="change" class="draft-change">{{ change }}</div>
            <div v-for="d in m.plans" :key="d.day_no" class="draft-day">
              <b>第{{ d.day_no }}天</b>：
              {{ (d.items || []).map((it) => it.poi_name).join(' → ') }}
            </div>
          </div>
          <div v-if="m.hotelOptions && m.hotelOptions.length" class="hotel-options-cta">
            <div class="hotel-options-cta-title">
              住宿备选方案（{{ m.hotelOptions.length }} 个，选择后才会应用）
            </div>
            <ul class="hotel-options-cta-list">
              <li v-for="option in m.hotelOptions" :key="option.id">
                {{ option.hotelName }} · {{ option.tier }}
                <span v-if="option.isCurrent">（当前）</span>
              </li>
            </ul>
            <el-button type="primary" size="small" @click="openHotelDialog(m, i)">
              查看并选择
            </el-button>
          </div>
        </li>
        <!-- 等待提示：role=status 隐式 polite，加载结束自动播报结束状态 -->
        <li v-if="nlLoading" class="chat-thinking" role="status">
          <el-icon class="is-loading"><Loading /></el-icon>
          {{ nlLoadingHint }}
        </li>
      </ul>
      <div class="chat-input">
        <el-input
          v-model="nlInstruction"
          placeholder="想怎么改？例如：换个酒店档次 / 调整某天节奏 / 删掉或替换某个景点"
          @keyup.enter="onChatSend"
        />
        <el-button :loading="nlLoading" @click="onChatSend">发送</el-button>
        <el-button :disabled="!chatMsgs.length" @click="onClearChat">清空对话</el-button>
        <el-button type="primary" :disabled="!draftChanged || !draftPlans.length" :loading="applying" @click="onApply">
          应用到行程
        </el-button>
      </div>
    </div>
    <HotelOptionsDialog
      v-model="hotelDialogVisible"
      :options="hotelDialogOptions"
      :selections="hotelDialogSelections"
      :message-id="hotelDialogMessageId"
      :base-revision="hotelDialogRevision"
      :itinerary-id="itineraryId"
      @applied="onHotelApplied"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'

import HotelOptionsDialog from '../HotelOptionsDialog.vue'
import { storeToRefs } from 'pinia'
import {
  chatEditItinerary,
  chatEditStreamItinerary,
  clearItineraryChatHistory,
  getItineraryChatHistory,
  type HotelOption,
} from '../../api/itinerary'
import { useItineraryStore } from '../../store/itinerary'
import {
  useItineraryActions,
  isAbortError,
  isCanceledError,
  errorMessageOf,
} from '../../composables/useItineraryActions'
import type { ItineraryChatMessage } from '../../types/chat'
import type { ChatDayPlan } from '../../types/chat'
import type { ItineraryDetail } from '../../types/itinerary'
import { renderMarkdown } from '../../utils/markdown'

// NL 编辑聊天面板（M4-②a §5.4）：流式打字机 + 草稿卡 + 酒店备选 CTA 原样迁出。
// 草稿数据源为 store.chatDraft；酒店选择持久态与 localStorage 读写收敛在 store 单点；
// 「应用到行程」成功后 emit('apply-draft') 由壳刷新 detail，本面板自行以服务端聊天记录对账。
const props = defineProps<{
  itineraryId: number | string
}>()

const emit = defineEmits<{
  'apply-draft': []
}>()

const store = useItineraryStore()
const actions = useItineraryActions()
const { detail, hotelSelections } = storeToRefs(store)

const nlInstruction = ref('')
const nlLoading = ref(false)
const nlLoadingHint = ref('正在理解需求并核对当前行程，请稍候…')
const nlOpen = ref(false)
const applying = ref(false)
const chatMsgs = ref<ItineraryChatMessage[]>([])
// 草稿数据源收敛到 store.chatDraft，computed 桥接保持模板与拆分前一致
const draftPlans = computed<ChatDayPlan[]>(() => store.chatDraft.plans ?? [])
const draftChanged = computed(() => !!store.chatDraft.changed)

const hotelDialogVisible = ref(false)
const hotelDialogOptions = ref<HotelOption[]>([])
const hotelDialogMessageId = ref<number | undefined>()
const hotelDialogRevision = ref<string | undefined>()
const hotelDialogSelections = ref<Record<string, { roomTypeId: string; dayNos: number[] }>>({})

const activeActionIndex = computed(() => {
  for (let i = chatMsgs.value.length - 1; i >= 0; i -= 1) {
    const message = chatMsgs.value[i]
    if (message.role === 'ai' && ((message.plans?.length || 0) > 0 || (message.hotelOptions?.length || 0) > 0)) {
      return i
    }
  }
  return -1
})

/** a11y：流式打字中的占位 AI 消息（尚无服务端 id）标记 aria-busy，避免逐 token 播报 */
function isStreaming(message: ItineraryChatMessage) {
  return nlLoading.value && message.role === 'ai' && !message.id
}

watch([chatMsgs, nlLoading], ([msgs, loading]) => {
  if (loading || msgs.length) nlOpen.value = true
}, { deep: true, immediate: false })

/** 拉取对话历史并初始化酒店选择/草稿（与拆分前 loadDetail 的对话侧逻辑一致）。 */
async function loadHistory() {
  const historyRes = await getItineraryChatHistory(props.itineraryId)
  chatMsgs.value = historyRes.data || []
  // 酒店选择恢复经 store 单点（解析失败按空处理，与既有行为一致）
  store.loadHotelSelections(props.itineraryId)
  for (const [index, message] of chatMsgs.value.entries()) {
    prepareHotelOptions(message, index)
  }
  const actionMessage = chatMsgs.value[activeActionIndex.value]
  store.setChatDraft({ plans: actionMessage?.plans || [], changed: !!actionMessage?.changed })
}

// 路由复用切换行程时随 itineraryId 重载（immediate 承接首次挂载）
watch(() => props.itineraryId, () => loadHistory(), { immediate: true })

async function onChatSend() {
  const message = nlInstruction.value.trim()
  if (!message || nlLoading.value || !detail.value) return
  const history = chatMsgs.value.map((m) => ({ role: m.role, content: m.content }))
  chatMsgs.value.push({ role: 'user', content: message })
  nlInstruction.value = ''
  nlLoading.value = true
  nlLoadingHint.value = '正在理解需求并核对当前行程，请稍候…'
  const controller = new AbortController()
  // Agent 自身最多等待模型 60 秒，再为服务间返回预留 10 秒，避免页面无限转圈。
  const hintTimer = window.setTimeout(() => {
    nlLoadingHint.value = '正在生成结构化修改草稿，复杂行程可能需要几十秒…'
  }, 12000)
  const timeout = window.setTimeout(() => controller.abort(), 70000)
  try {
    // 主路径：SSE 流式：token 打字机渲染进占位 AI 消息；
    // 除中止外的任何失败回退到 70s 阻塞端点，两条路径的落库语义一致。
    const placeholder: ItineraryChatMessage = {
      role: 'ai',
      content: '',
      plans: [],
      hotelOptions: [],
      changed: false,
    }
    chatMsgs.value.push(placeholder)
    try {
      await chatEditStreamItinerary(
        detail.value.id,
        { message, history },
        {
          onToken: (delta) => {
            placeholder.content += delta
          },
          onDraft: (payload) => {
            const plans = payload.plans || []
            const hotelOptions = payload.hotelOptions || []
            if (plans.length || hotelOptions.length) {
              const replacedPending = activeActionIndex.value >= 0
              for (const previous of chatMsgs.value) {
                if (previous.role === 'ai' && previous !== placeholder) {
                  previous.plans = []
                  previous.hotelOptions = []
                  previous.changed = false
                }
              }
              if (replacedPending) ElMessage.info('本轮建议已替代上一份未应用方案')
            }
            placeholder.id = payload.messageId
            placeholder.plans = plans
            placeholder.hotelOptions = hotelOptions
            placeholder.changed = !!payload.changed
            placeholder.baseRevision = payload.baseRevision
            prepareHotelOptions(placeholder, chatMsgs.value.length - 1)
            store.setChatDraft({ plans, changed: !!payload.changed })
          },
        },
        controller.signal,
      )
      return
    } catch (streamError) {
      // 流式占位消息不再需要：回退路径会重新生成完整回复
      const placeholderIndex = chatMsgs.value.indexOf(placeholder)
      if (placeholderIndex >= 0) chatMsgs.value.splice(placeholderIndex, 1)
      if (isAbortError(streamError)) {
        chatMsgs.value.push({
          role: 'ai',
          content: '### 本次处理超时\n\n行程没有被修改。请稍后重试，或把要求拆成更短的一步再发送。',
        })
        return
      }
      // 其它失败（网络/协议/Agent error 事件）→ 走阻塞端点
    }
    const res = await chatEditItinerary(detail.value.id, message, history, controller.signal)
    const plans = res.data.plans || []
    const hotelOptions = res.data.hotelOptions || []
    if (plans.length || hotelOptions.length) {
      const replacedPending = activeActionIndex.value >= 0
      for (const previous of chatMsgs.value) {
        if (previous.role === 'ai') {
          previous.plans = []
          previous.hotelOptions = []
          previous.changed = false
        }
      }
      if (replacedPending) ElMessage.info('本轮建议已替代上一份未应用方案')
    }
    const aiMessage: ItineraryChatMessage = {
      id: res.data.messageId,
      role: 'ai',
      content: res.data.reply,
      plans,
      hotelOptions,
      changed: res.data.changed,
      baseRevision: res.data.baseRevision,
    }
    chatMsgs.value.push(aiMessage)
    prepareHotelOptions(aiMessage, chatMsgs.value.length - 1)
    store.setChatDraft({ plans, changed: res.data.changed })
  } catch (err) {
    const aborted = isCanceledError(err)
    const errorMessage = errorMessageOf(err)
    chatMsgs.value.push({
      role: 'ai',
      content: aborted
        ? '### 本次处理超时\n\n行程没有被修改。请稍后重试，或把要求拆成更短的一步再发送。'
        : (errorMessage ? `处理失败：${errorMessage}` : '这条没太理解，换个说法试试？'),
    })
  } finally {
    clearTimeout(hintTimer)
    clearTimeout(timeout)
    nlLoading.value = false
  }
}

async function onClearChat() {
  if (!detail.value || !chatMsgs.value.length) return
  try {
    await ElMessageBox.confirm('确认清空当前行程的全部对话记录？行程本身不会受到影响。', '清空对话', {
      type: 'warning',
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await clearItineraryChatHistory(detail.value.id)
  chatMsgs.value = []
  // 酒店选择与草稿清空均经 store 单点（含 localStorage 清理）
  store.clearHotelSelections(props.itineraryId)
  store.clearChatDraft()
  ElMessage.success('对话记录已清空')
}

function selectionKey(message: ItineraryChatMessage, index: number, option: HotelOption) {
  return `${message.id ?? `local-${index}`}:${option.id}`
}

function defaultSelection(option: HotelOption) {
  const defaultRoom = option.roomTypes.find((room) => room.isDefault) || option.roomTypes[0]
  const presetDays = option.requestedDayNos?.length === option.requestedNights
    ? [...option.requestedDayNos]
    : option.requestedNights === option.availableDayNos.length
      ? [...option.availableDayNos]
      : []
  return {
    roomTypeId: defaultRoom?.id || '',
    dayNos: presetDays,
  }
}

function prepareHotelOptions(message: ItineraryChatMessage, index: number) {
  for (const option of message.hotelOptions || []) {
    const key = selectionKey(message, index, option)
    if (hotelSelections.value[key]) continue
    hotelSelections.value[key] = defaultSelection(option)
  }
}

function openHotelDialog(message: ItineraryChatMessage, index: number) {
  const options = message.hotelOptions || []
  if (!options.length || !detail.value) return
  prepareHotelOptions(message, index)
  const map: Record<string, { roomTypeId: string; dayNos: number[] }> = {}
  for (const option of options) {
    const key = selectionKey(message, index, option)
    const source = hotelSelections.value[key] || defaultSelection(option)
    map[option.id] = { roomTypeId: source.roomTypeId, dayNos: [...source.dayNos] }
  }
  hotelDialogSelections.value = map
  hotelDialogOptions.value = options
  hotelDialogMessageId.value = message.id
  hotelDialogRevision.value = message.baseRevision
  hotelDialogVisible.value = true
}

function onHotelApplied(nextDetail: ItineraryDetail) {
  store.setDetail(nextDetail)
  store.setChatDraft({ changed: false })
  const target = chatMsgs.value.find((m) => m.id === hotelDialogMessageId.value)
    ?? chatMsgs.value[activeActionIndex.value]
  if (target) target.hotelOptions = []
}

function draftChanges(message: ItineraryChatMessage) {
  if (!detail.value) return []
  const changes: string[] = []
  for (const plan of message.plans || []) {
    const currentDay = detail.value.dayList.find((day) => day.dayNo === plan.day_no)
    const currentItems = currentDay?.items || []
    const nextItems = plan.items || []
    const currentNames = currentItems.map((item) => item.poiName)
    const nextNames = nextItems.map((item) => item.poi_name ?? '')
    const removed = currentNames.filter((name) => !nextNames.includes(name))
    const added = nextNames.filter((name) => !currentNames.includes(name))
    if (removed.length) changes.push(`第${plan.day_no}天删除：${removed.join('、')}`)
    if (added.length) changes.push(`第${plan.day_no}天新增：${added.join('、')}`)
    if (!removed.length && !added.length && currentNames.join('|') !== nextNames.join('|')) {
      changes.push(`第${plan.day_no}天调整游览顺序`)
    }
    const timeChanged = nextItems.some((item) => {
      const current = currentItems.find((row) => row.poiName === item.poi_name)
      return current && (current.startTime || '') !== (item.start_time || '')
    })
    if (timeChanged) changes.push(`第${plan.day_no}天调整时间安排`)
  }
  return changes.length ? changes : ['计划内容已更新，请核对下方完整安排']
}

async function onApply() {
  if (!detail.value || !draftChanged.value || applying.value) return
  const actionMessage = chatMsgs.value[activeActionIndex.value]
  if (!actionMessage?.id) {
    ElMessage.warning('该草稿缺少确认信息，请重新生成')
    return
  }
  applying.value = true
  try {
    await actions.applyPlans(detail.value.id, draftPlans.value, actionMessage.id, actionMessage.baseRevision)
    ElMessage.success('已应用到行程')
    actionMessage.plans = []
    store.setChatDraft({ changed: false })
    // 与拆分前全量重载语义一致：壳刷新 detail（含手风琴复位），聊天侧以服务端记录对账
    emit('apply-draft')
    await loadHistory()
  } catch {
    // 错误提示已由拦截器处理
  } finally {
    applying.value = false
  }
}
</script>

<style scoped>
.nl-edit {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed var(--lp-border);
}

.nl-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 44px;
  padding: 10px 14px;
  border: 1px solid var(--lp-border);
  border-radius: 12px;
  background: var(--lp-sand);
  color: var(--lp-ink);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.nl-toggle:hover {
  border-color: var(--lp-accent);
  background: var(--lp-accent-soft);
}

.nl-toggle-hint {
  font-size: 12px;
  font-weight: 500;
  color: var(--lp-muted);
}

.nl-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.chat-scroll {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 6px;
}

.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 10px 0 6px;
  color: var(--lp-ink);
  line-height: 1.35;
}

.markdown-body :deep(h3) {
  font-size: 16px;
}

.markdown-body :deep(p) {
  margin: 5px 0;
  line-height: 1.7;
}

.markdown-body :deep(ul) {
  margin: 6px 0;
  padding-left: 22px;
}

.markdown-body :deep(li) {
  margin: 4px 0;
  line-height: 1.65;
}

.markdown-body :deep(code) {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgb(0 0 0 / 6%);
}

.draft-preview {
  margin-top: 8px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
  font-size: 13px;
  color: var(--lp-ink-soft);
}

.draft-day {
  padding: 2px 0;
}

.chat-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  margin: 8px 0;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--lp-sand);
  color: var(--lp-ink-soft);
  font-size: 13px;
}

.draft-summary-title {
  margin-bottom: 4px;
  font-weight: 700;
  color: var(--lp-ink);
}

.draft-change {
  margin-bottom: 3px;
  color: var(--lp-accent-hover);
}

/* 聊天内住宿备选：摘要卡片，详情走 Dialog */
.hotel-options-cta {
  margin-top: 10px;
  padding: 12px 14px;
  background: var(--lp-paper);
  border: 1px solid var(--lp-border);
  border-radius: 10px;
}

.hotel-options-cta-title {
  font-weight: 700;
  color: var(--lp-ink);
  font-size: 13px;
  margin-bottom: 6px;
}

.hotel-options-cta-list {
  margin: 0 0 10px;
  padding-left: 18px;
  color: var(--lp-ink-soft);
  font-size: 13px;
  line-height: 1.7;
}

.chat-input {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chat-input :deep(.el-input) {
  flex: 1 1 220px;
  min-width: 0;
}
</style>
