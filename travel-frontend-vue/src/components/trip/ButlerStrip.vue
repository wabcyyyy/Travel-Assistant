<template>
  <section class="butler-strip" :class="{ 'is-generating': detail.status === 1 }">
    <div class="strip-row">
      <span class="strip-label">AI 管家说</span>
      <p class="strip-preview">{{ preview }}</p>
      <span v-if="weatherChip" class="strip-chip weather-chip" title="出发前天气预报，出发前请以实际天气为准">
        {{ weatherChip }}
      </span>
      <span class="strip-chip" :class="`tone-${statusChip.tone}`">{{ statusChip.text }}</span>
      <div class="strip-actions">
        <button
          type="button"
          class="strip-btn"
          :aria-expanded="expanded ? 'true' : 'false'"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起' : '展开' }}
          <ChevronDown :size="15" class="chev" :class="{ 'is-open': expanded }" />
        </button>
        <button v-if="canEdit !== true" type="button" class="strip-btn" @click="emit('chat')">
          <MessageCircle :size="14" /> 对话
        </button>
        <button type="button" class="strip-btn" @click="emit('versions')">版本历史</button>
      </div>
    </div>
    <div v-show="expanded" class="strip-body">
      <HeadStatusPanel
        :detail="detail"
        :done-days="doneDays"
        :stream-state="streamState"
        :weather="weather"
        @retry="emit('retry')"
      />
      <ButlerNoteCard
        v-if="detail.planNote && detail.status !== 3"
        :note="detail.planNote"
        :streaming="streamState.phase === 'butler'"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, MessageCircle } from 'lucide-vue-next'

import { fetchItineraryWeather } from '../../api/weather'
import type { StreamState } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'
import type { WeatherVO } from '../../types/generated/contracts'
import ButlerNoteCard from './ButlerNoteCard.vue'
import HeadStatusPanel from './HeadStatusPanel.vue'

// 「管家说」条（v2.6 §19.3）：页头通栏一行 = 手记首句 + 生成状态 chip + 展开。
// 展开体 = HeadStatusPanel（进度/降级/重试全量）+ 管家信件（ButlerNoteCard）。
// 生成失败自动展开（让重试按钮可见）；对话与版本历史入口收在本条右侧。
const props = defineProps<{
  detail: ItineraryDetail
  doneDays: number
  streamState: StreamState
  /** 协作（C2.3）：viewer 隐藏「对话」写入口（后端闸门为准，这里只藏入口） */
  canEdit?: boolean
}>()
const emit = defineEmits<{
  retry: []
  chat: []
  versions: []
}>()

const expanded = ref(false)

// ---------- 出发前天气（C3.1）----------
// 免 key 预报属增强信息：取不到（超 16 天窗/无坐标/上游失败）一律静默隐藏，
// 不进 statusChip 的状态语义，也不触发错误提示（接口侧 skipErrorMessage）。
const weather = ref<WeatherVO | null>(null)

// 天气属于"这条行程"的事实：本组件在 /trips/1 → /trips/2 之间是被复用的
// （父级只 v-if="detail"，实例不重建），只在 onMounted 取一次会让 B 显示 A 的天气。
// 口径照抄 ExpensePanel 的既有写法：watch id + 请求序号，旧响应不得覆盖新值。
let weatherRequestId = 0
async function loadWeather(itineraryId: number) {
  const id = ++weatherRequestId
  weather.value = null // 换行程先撤下上一个城市的天气，别在新响应落地前继续挂着它
  try {
    const res = await fetchItineraryWeather(itineraryId)
    if (id === weatherRequestId) weather.value = res.data
  } catch {
    if (id === weatherRequestId) weather.value = null
  }
}

watch(() => props.detail.id, (id) => void loadWeather(id), { immediate: true })

function shortDay(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : `${d.getMonth() + 1}/${d.getDate()}`
}

const weatherChip = computed(() => {
  const first = weather.value?.daily?.[0]
  if (!first) return null
  const temp
    = first.tMin != null && first.tMax != null ? ` ${Math.round(first.tMin)}~${Math.round(first.tMax)}°C` : ''
  return `${shortDay(first.date)} ${first.text}${temp}`
})

/** 摘要 = 手记首个非空、非预约提醒行；无手记时给生成态/空态文案 */
const preview = computed(() => {
  const raw = (props.detail.planNote || '').replace(/\\n/g, '\n')
  const first = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('【预约提醒】'))[0]
  if (first) return first
  return props.detail.status === 1 ? '正在为你整理这趟行程，完成后在这里汇报。' : '暂无管家手记'
})

interface StatusChip {
  text: string
  tone: 'accent' | 'success' | 'warning' | 'danger'
}

const statusChip = computed<StatusChip>(() => {
  const d = props.detail
  if (d.status === 1) {
    const phase = props.streamState.phase
    if (phase === 'failed') {
      return { text: props.streamState.errorMessage || '生成中断', tone: 'danger' }
    }
    if (props.streamState.fallbackMode) {
      return { text: `排版中 ${props.doneDays}/${d.days} 天 · 保守模式`, tone: 'warning' }
    }
    if (phase === 'day' && props.streamState.dayNo != null) {
      return { text: `排版中 · 第 ${props.streamState.dayNo}/${d.days} 天`, tone: 'accent' }
    }
    if (phase === 'butler') return { text: '管家撰写中', tone: 'accent' }
    return { text: '汇编资料中', tone: 'accent' }
  }
  if (d.status === 3) return { text: '生成失败', tone: 'danger' }
  if (props.streamState.degradedDays.length) {
    return { text: `部分完成（第 ${props.streamState.degradedDays.join('、')} 天）`, tone: 'warning' }
  }
  if (props.streamState.degraded.length) return { text: '部分降级', tone: 'warning' }
  return { text: '已完成', tone: 'success' }
})

// 失败态自动展开（重试按钮可见）：含初始即 failed（断线重连/刷新进失败态）的场景
watch(
  () => props.streamState.phase,
  (phase) => {
    if (phase === 'failed') expanded.value = true
  },
  { immediate: true },
)
</script>

<style scoped>
.butler-strip {
  margin-bottom: var(--lp-space-4);
  padding: 10px 16px;
  background: var(--lp-surface-card);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
}

.strip-row {
  display: flex;
  align-items: center;
  gap: var(--lp-space-3);
}

.strip-label {
  flex: none;
  font-size: 12.5px;
  font-weight: 800;
  letter-spacing: 0.12em;
  color: var(--lp-accent);
}

.strip-preview {
  flex: 1;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--lp-text-2);
  font-size: 13px;
}

.strip-chip {
  flex: none;
  padding: 2px 10px;
  border-radius: var(--lp-radius-pill);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.tone-accent {
  background: var(--lp-accent-subtle);
  color: var(--lp-accent-hover);
}

.tone-success {
  background: var(--lp-success-soft);
  color: var(--lp-success);
}

.tone-warning {
  background: var(--lp-warning-soft);
  color: var(--lp-warning);
}

.tone-danger {
  background: var(--lp-danger-soft);
  color: var(--lp-danger);
}

/* 天气 chip（C3.1）：中性底色，与状态 chip 的语义色区分 */
.weather-chip {
  background: var(--lp-sand);
  border: 1px solid var(--lp-border);
  color: var(--lp-ink-soft);
}

.strip-actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
}

.strip-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: none;
  border-radius: var(--lp-radius-xs);
  background: transparent;
  color: var(--lp-text-muted);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.strip-btn:hover {
  background: var(--lp-surface-hover);
  color: var(--lp-text-1);
}

.chev {
  transition: transform 0.15s ease;
}

.chev.is-open {
  transform: rotate(180deg);
}

.strip-body {
  margin-top: var(--lp-space-3);
  padding-top: var(--lp-space-3);
  border-top: 1px solid var(--lp-edge-faint);
}

/* ---------- 桌面（≥768）压缩成 h40 细条（v2.7 §20 R1）----------
   位置由详情页壳设定（fixed top:62 横跨工作台），这里只管形状与材质：
   一行放完「标签 + 摘句 + 状态 chip + 展开/对话/版本」；展开体改为下挂浮层，
   不吃工作台高度（工作台也是 fixed，撑高会把它顶走） */
@media (min-width: 768px) {
  .butler-strip {
    position: relative;
    display: flex;
    align-items: center;
    min-height: 40px;
    margin: 0;
    padding: 0 var(--lp-space-3);
    background: var(--lp-panel-bg);
    backdrop-filter: var(--lp-panel-blur);
    -webkit-backdrop-filter: var(--lp-panel-blur);
    border: none;
    border-radius: var(--lp-radius-sm);
    box-shadow: var(--lp-panel-shadow);
  }

  .strip-row {
    flex: 1;
    min-width: 0;
    gap: var(--lp-space-2);
  }

  .strip-label {
    font-size: 11px;
    letter-spacing: 0.08em;
  }

  .strip-preview {
    font-size: 12.5px;
  }

  .strip-body {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    z-index: var(--lp-z-panel);
    max-height: 62vh;
    margin: 0;
    padding: var(--lp-space-4);
    overflow: auto;
    background: var(--lp-panel-bg);
    backdrop-filter: var(--lp-panel-blur);
    -webkit-backdrop-filter: var(--lp-panel-blur);
    border-top: none;
    border-radius: var(--lp-radius-sm);
    box-shadow: var(--lp-panel-shadow);
  }
}

@media (max-width: 767px) {
  .strip-row {
    flex-wrap: wrap;
  }

  .strip-preview {
    order: 3;
    flex-basis: 100%;
    white-space: normal;
  }
}
</style>
