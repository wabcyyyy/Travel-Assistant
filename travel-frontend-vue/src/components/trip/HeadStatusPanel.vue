<template>
  <div v-if="detail.status === 3" class="gen-banner error">
    <span>{{ detail.planNote || '行程生成失败，请重新生成' }}</span>
  </div>

  <!-- §5.3.5 流式进度：store.streamState 状态机驱动，替换旧「已完成 x/y 天」轮询 banner -->
  <template v-if="detail.status === 1">
    <!-- 保守模式（SSE 3 连败回退轮询）：无 shimmer，仅静态进度文案 -->
    <div v-if="streamState.fallbackMode" class="stream-lines" role="status" aria-live="polite">
      <p class="stream-line">排版中：已完成 {{ doneDays }} / {{ detail.days }} 天…</p>
    </div>
    <!-- 研究阶段：头部骨架 shimmer（reduce 下退化为静态骨架条 + 静态文案） -->
    <div v-else-if="showResearchSkeleton" class="stream-skeleton" role="status" aria-live="polite">
      <span class="lp-skel-line sk-head-a"></span>
      <span class="lp-skel-line sk-head-b"></span>
      <span class="sk-caption">汇编目的地资料…</span>
    </div>
    <!-- 研究完成 + 逐日进度 -->
    <div v-else class="stream-lines" role="status" aria-live="polite">
      <p v-if="streamState.evidenceCount != null" class="stream-line">
        资料汇编完成，共 {{ streamState.evidenceCount }} 条素材
        <span v-if="researchDegraded" class="stream-warn">部分素材降级</span>
      </p>
      <p v-if="streamState.phase === 'day'" class="stream-line">
        {{ dayProgressText }}
        <span v-if="doneDays >= 1" class="stream-hint">已排好的页面可在下方查看</span>
      </p>
    </div>
    <!-- error 事件：retryable → 重试按钮（壳重新 loadDetail + 重订阅）；不可重试 → 失败态 -->
    <div v-if="streamState.phase === 'failed'" class="gen-banner error">
      <span>{{ failText }}</span>
      <button v-if="streamState.retryable" type="button" class="retry-btn" @click="emit('retry')">重试</button>
    </div>
  </template>

  <!-- complete(PARTIAL)：degradedDays 如实展示，不隐藏 -->
  <div v-if="partialNotice" class="gen-banner warn">
    <span>{{ partialNotice }}</span>
  </div>
  <VerificationNotice />
  <div class="head-info">
    <div v-if="weather?.daily?.length" class="weather-days" role="note" aria-label="出发前天气预报">
      <span v-for="day in weather.daily" :key="day.date" class="meta-chip weather-day">
        <CloudSun :size="13" class="weather-ico" />
        {{ shortDay(day.date) }} {{ day.text }}<template v-if="day.tMin != null && day.tMax != null">
          {{ Math.round(day.tMin) }}~{{ Math.round(day.tMax) }}°C</template>
      </span>
    </div>
    <div v-if="detail.preferences" class="meta-chips">
      <span class="meta-chip">偏好：{{ detail.preferences }}</span>
    </div>
    <p v-if="dateNightMismatch" class="mismatch-line">
      <el-tag type="warning" size="small">
        日期通常对应 {{ expectedDateNights }} 晚，当前计划含 {{ detail.stayNights }} 晚
      </el-tag>
    </p>
  </div>
  <!-- 断线降级：用户仅见底部状态条（轮询兜底已由壳接手） -->
  <div v-if="detail.status === 1 && streamState.fallbackMode" class="stream-fallback">
    网络不稳定，已切换保守模式
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CloudSun } from 'lucide-vue-next'

import VerificationNotice from './VerificationNotice.vue'

import type { StreamState } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'
import type { WeatherVO } from '../../types/generated/contracts'

// head 卡状态区（M4-②a §5.4 / M4-②b §5.3.5 流式升级）：
// 生成进度由 store.streamState 驱动（idle/researching/day/butler/complete/failed +
// degraded[]/degradedDays[]/fallbackMode/retryable），轮询 doneDays 仅作保守模式兜底文案。
// 多根组件不引入包裹层，避免改变 head 卡内的布局结构。
const props = defineProps<{
  detail: ItineraryDetail
  /** 已完成天数（保守模式轮询进度兜底用） */
  doneDays: number
  /** SSE 生成进度状态机（store.streamState） */
  streamState: StreamState
  /** 出发前天气（C3.1）：ButlerStrip 取数后下传；null/无数据即不渲染（静默） */
  weather?: WeatherVO | null
}>()

const emit = defineEmits<{
  /** error(retryable) 的重试：壳重新 loadDetail + 重订阅 */
  retry: []
}>()

// ---------- §5.3.5 状态 → UI 映射 ----------

/** 研究阶段骨架：尚未收到 research_done（evidenceCount 为空）且链路未降级 */
const showResearchSkeleton = computed(
  () =>
    !props.streamState.fallbackMode &&
    props.streamState.evidenceCount == null &&
    (props.streamState.phase === 'idle' || props.streamState.phase === 'researching'),
)

/** research_done：degraded 标记落在研究环节时附「部分证据降级」 */
const researchDegraded = computed(() =>
  props.streamState.degraded.some((d) => /research|研究|证据/i.test(d.scope)),
)

/** day 相位进度文案（reduce 模式下同为此静态文案，shimmer 只在骨架层） */
const dayProgressText = computed(() => {
  const dayNo = props.streamState.dayNo
  if (dayNo != null && dayNo <= props.detail.days) {
    return `排版中 · 第 ${dayNo} / ${props.detail.days} 天`
  }
  return '逐日排版完成，AI 管家撰写中…'
})

/** error 事件：优先透出后端 message */
const failText = computed(() => props.streamState.errorMessage || '行程生成中断，请稍后重试')

/** complete(PARTIAL)：保留 degradedDays 列表如实展示 */
const partialNotice = computed(() => {
  if (props.streamState.phase !== 'complete' || !props.streamState.degradedDays.length) return ''
  return `行程已生成，第 ${props.streamState.degradedDays.join('、')} 天未成功，其余内容可用`
})

const expectedDateNights = computed(() => {
  const d = props.detail
  if (!d.startDate || !d.endDate) return null
  const difference = new Date(d.endDate).getTime() - new Date(d.startDate).getTime()
  return Math.max(Math.round(difference / 86400000), 0)
})
const dateNightMismatch = computed(() => expectedDateNights.value != null
  && props.detail.stayNights !== expectedDateNights.value)

function shortDay(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : `${d.getMonth() + 1}/${d.getDate()}`
}
</script>

<style scoped>
.gen-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid var(--lp-border);
  border-left: 4px solid var(--lp-accent);
  border-radius: 8px;
  background: var(--lp-sand);
  font-weight: 600;
}

.gen-banner.error {
  border-left-color: var(--lp-danger);
  background: var(--el-color-danger-light-9);
}

.gen-banner.warn {
  border-left-color: #e6a23c;
  background: var(--el-color-warning-light-9);
  font-weight: 500;
  flex-wrap: wrap;
}

/* ---------- §5.3.5 流式进度 ---------- */
.stream-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.sk-head-a {
  width: 46%;
}

.sk-head-b {
  width: 72%;
  height: 14px;
}

.sk-caption {
  font-family: var(--lp-font-data);
  font-size: 11.5px;
  color: var(--lp-why-ink);
}

.stream-lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.stream-line {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--lp-ink-soft);
}

.stream-hint {
  margin-left: 8px;
  font-weight: 400;
  font-size: 12.5px;
  color: var(--lp-muted);
}

.stream-warn {
  margin-left: 8px;
  padding: 1px 8px;
  border: 1px solid var(--lp-warning);
  border-radius: 999px;
  background: var(--el-color-warning-light-9);
  font-size: 11px;
  font-weight: 500;
  color: var(--lp-why-ink);
}

.retry-btn {
  margin-left: auto;
  flex-shrink: 0;
  padding: 2px 12px;
  border: 1px solid currentColor;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.stream-fallback {
  margin-top: 10px;
  padding: 6px 12px;
  border: 1px dashed var(--lp-rule);
  border-radius: 8px;
  background: var(--lp-sand);
  font-size: 12.5px;
  color: var(--lp-why-ink);
}

.head-info p {
  margin: 4px 0;
  color: var(--el-text-color-secondary);
}

/* ---------- 元信息胶囊（偏好） ---------- */
.meta-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--lp-sand);
  border: 1px solid var(--lp-border);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--lp-ink-soft);
  font-variant-numeric: tabular-nums;
}

/* ---------- 出发前天气（C3.1）---------- */
.weather-days {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.weather-day {
  gap: 4px;
  font-variant-numeric: tabular-nums;
}

.weather-ico {
  flex: none;
  color: var(--lp-accent);
}

.mismatch-line {
  margin: 10px 0 0;
}
</style>
