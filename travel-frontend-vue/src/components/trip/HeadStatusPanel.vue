<template>
  <div v-if="detail.status === 3" class="gen-banner error">
    <span>{{ detail.planNote || '行程生成失败，请重新生成' }}</span>
  </div>

  <!-- §5.3.5 流式进度：store.streamState 状态机驱动，替换旧「已完成 x/y 天」轮询 banner -->
  <template v-if="detail.status === 1">
    <!-- 保守模式（SSE 3 连败回退轮询）：无 shimmer，仅静态进度文案 -->
    <div v-if="streamState.fallbackMode" class="stream-lines" role="status" aria-live="polite">
      <p class="stream-line">生成中：已完成 {{ doneDays }} / {{ detail.days }} 天…</p>
    </div>
    <!-- 研究阶段：头部骨架 shimmer（reduce 下退化为静态骨架条 + 静态文案） -->
    <div v-else-if="showResearchSkeleton" class="stream-skeleton" role="status" aria-live="polite">
      <span class="lp-skel-line sk-head-a"></span>
      <span class="lp-skel-line sk-head-b"></span>
      <span class="sk-caption">正在研究目的地…</span>
    </div>
    <!-- 研究完成 + 逐日进度 -->
    <div v-else class="stream-lines" role="status" aria-live="polite">
      <p v-if="streamState.evidenceCount != null" class="stream-line">
        研究完成：{{ streamState.evidenceCount }} 条证据
        <span v-if="researchDegraded" class="stream-warn">部分证据降级</span>
      </p>
      <p v-if="streamState.phase === 'day'" class="stream-line">
        {{ dayProgressText }}
        <span v-if="doneDays >= 1" class="stream-hint">已生成部分可在下方查看</span>
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

  <div v-if="showDegradedBanner" class="gen-banner warn">
    <span class="degraded-title">部分信息需复核</span>
    <span>{{ degradedBannerText }}</span>
    <button type="button" class="degraded-help-toggle" @click="reviewHelpOpen = !reviewHelpOpen">
      {{ reviewHelpOpen ? '收起说明' : '如何复核？' }}
    </button>
  </div>
  <div v-if="showDegradedBanner && reviewHelpOpen" class="review-help">
    <ol>
      <li>在下方行程中筛选带「待确认 / 参考估算」标签的点位</li>
      <li>出发前用地图 App 或景点官网核实：<b>是否仍营业</b>、<b>营业时间</b>、<b>票价/预约</b></li>
      <li>价格仅作预算参考，以现场/官方购票页为准；开放研究草案的点位尤其要核对</li>
      <li>可在本页「智能修改」里让 AI 换成更稳妥的点位</li>
    </ol>
  </div>
  <div class="head-info">
    <div v-if="detail.preferences" class="meta-chips">
      <span class="meta-chip">偏好：{{ detail.preferences }}</span>
    </div>
    <p v-if="dateNightMismatch" class="mismatch-line">
      <el-tag type="warning" size="small">
        日期通常对应 {{ expectedDateNights }} 晚，当前计划含 {{ detail.stayNights }} 晚
      </el-tag>
    </p>
    <p v-if="detail.destinationStatus || detail.qualityStatus" class="quality-summary">
      <el-tag v-if="detail.destinationStatus" size="small" type="info">
        {{ destinationStatusLabel(detail.destinationStatus) }}
      </el-tag>
      <el-tag v-if="detail.qualityStatus" size="small" :type="qualityTagType(detail.qualityStatus)" style="margin-left: 6px">
        {{ qualityStatusLabel(detail.qualityStatus) }}
      </el-tag>
      <span v-if="detail.pendingFactCount" class="quality-hint">
        {{ detail.pendingFactCount }} 项信息需要出发前复核
      </span>
    </p>
  </div>
  <!-- 断线降级：用户仅见底部状态条（轮询兜底已由壳接手） -->
  <div v-if="detail.status === 1 && streamState.fallbackMode" class="stream-fallback">
    网络不稳定，已切换保守模式
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import type { StreamState } from '../../store/itinerary'
import type { ItineraryDetail } from '../../types/itinerary'

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
}>()

const emit = defineEmits<{
  /** error(retryable) 的重试：壳重新 loadDetail + 重订阅 */
  retry: []
}>()

const reviewHelpOpen = ref(false)

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
    return `生成中 · 第 ${dayNo} / ${props.detail.days} 天`
  }
  return '逐日行程完成，正在整理管家讲解…'
})

/** error 事件：优先透出后端 message */
const failText = computed(() => props.streamState.errorMessage || '行程生成中断，请稍后重试')

/** complete(PARTIAL)：保留 degradedDays 列表如实展示 */
const partialNotice = computed(() => {
  if (props.streamState.phase !== 'complete' || !props.streamState.degradedDays.length) return ''
  return `行程已生成，第 ${props.streamState.degradedDays.join('、')} 天未成功，其余内容可用`
})

/** 降级/待复核横幅：对齐产品「如实降级」叙事，不把风险藏在小标签里。 */
const showDegradedBanner = computed(() => {
  const d = props.detail
  if (d.status === 1 || d.status === 3) return false
  if (d.destinationStatus === 'draft_only') return true
  if (d.qualityStatus === 'READY_WITH_WARNINGS' || d.qualityStatus === 'STALE' || d.qualityStatus === 'BLOCKED') {
    return true
  }
  return Boolean(d.pendingFactCount && d.pendingFactCount > 0)
})

const degradedBannerText = computed(() => {
  const d = props.detail
  const parts: string[] = []
  if (d.destinationStatus === 'draft_only') {
    parts.push('当前为开放研究草案，点位请出发前核实营业与票价')
  }
  const issues = d.qualityReport?.warnings?.map((w) => w.message).filter(Boolean).slice(0, 2) || []
  if (issues.length) {
    parts.push(issues.join('；'))
  } else if (d.qualityStatus === 'READY_WITH_WARNINGS') {
    parts.push('行程可用，但存在需关注的约束提示')
  }
  if (d.qualityStatus === 'BLOCKED') {
    const blocking = d.qualityReport?.blockingIssues?.map((b) => b.message).filter(Boolean).slice(0, 1) || []
    parts.push(blocking[0] || '质量检查未全部通过，请复核时间与路线')
  }
  if (d.pendingFactCount && d.pendingFactCount > 0) {
    parts.push(`${d.pendingFactCount} 项事实标记为出发前复核`)
  }
  return parts.join('；')
})

const expectedDateNights = computed(() => {
  const d = props.detail
  if (!d.startDate || !d.endDate) return null
  const difference = new Date(d.endDate).getTime() - new Date(d.startDate).getTime()
  return Math.max(Math.round(difference / 86400000), 0)
})
const dateNightMismatch = computed(() => expectedDateNights.value != null
  && props.detail.stayNights !== expectedDateNights.value)

function destinationStatusLabel(status?: ItineraryDetail['destinationStatus']) {
  if (status === 'researched') return '外部研究'
  if (status === 'draft_only') return '探索草案'
  return '知识库支持'
}

function qualityStatusLabel(status?: ItineraryDetail['qualityStatus']) {
  if (status === 'READY') return '已通过质量检查'
  if (status === 'READY_WITH_WARNINGS') return '可用，但需注意提示'
  if (status === 'STALE') return '信息已过期'
  if (status === 'BLOCKED') return '质量检查未通过'
  return '草稿'
}

function qualityTagType(status?: ItineraryDetail['qualityStatus']) {
  if (status === 'READY') return 'success'
  if (status === 'BLOCKED') return 'danger'
  if (status === 'STALE') return 'danger'
  return 'warning'
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

.gen-banner.warn .degraded-title {
  flex-shrink: 0;
  font-weight: 700;
}

.gen-banner.warn .degraded-help-toggle {
  margin-left: auto;
  flex-shrink: 0;
  border: 1px solid currentColor;
  background: transparent;
  color: inherit;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
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
  font-size: 12px;
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
  font-size: 12px;
  cursor: pointer;
}

.stream-fallback {
  margin-top: 10px;
  padding: 6px 12px;
  border: 1px dashed var(--lp-rule);
  border-radius: 8px;
  background: var(--lp-sand);
  font-size: 12px;
  color: var(--lp-why-ink);
}

.review-help {
  margin: -4px 0 14px;
  padding: 10px 14px 10px 32px;
  border: 1px solid var(--lp-border);
  border-left: 4px solid #e6a23c;
  border-radius: 8px;
  background: var(--lp-paper);
  font-size: 13px;
  line-height: 1.6;
  color: var(--lp-ink);
}

.review-help ol {
  margin: 0;
  padding-left: 1em;
}

.review-help li + li {
  margin-top: 4px;
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

.mismatch-line {
  margin: 10px 0 0;
}
</style>
