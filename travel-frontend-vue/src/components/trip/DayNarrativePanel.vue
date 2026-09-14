<template>
  <div v-if="hasNarrative" class="day-narrative">
    <!-- theme 不在此重复展示：日卡 summary 已用衬线大字渲染（旧版两处重复撑高页面） -->

    <!-- note：本章导语正文 -->
    <p v-if="day.note" class="narr-note">{{ day.note }}</p>

    <!-- practical_notes：--lp-note-callout 浅青灰底 + 左 3px 主题渐变竖线，逐行可执行提示 -->
    <ul v-if="practicalNotes.length" class="narr-callout">
      <li v-for="(n, i) in practicalNotes" :key="i">{{ n }}</li>
    </ul>

    <!-- photo_spots：--lp-photo-badge 浅底深字徽标行，best_time 用 data mono -->
    <div v-if="photoSpots.length" class="narr-photos">
      <span class="photos-label">拍照机位</span>
      <span v-for="(s, i) in photoSpots" :key="i" class="photo-badge">
        <span class="photo-name">{{ spotName(s) }}</span>
        <span v-if="s.tip" class="photo-tip">{{ s.tip }}</span>
        <span v-if="s.bestTime" class="photo-time">{{ s.bestTime }}</span>
      </span>
    </div>

    <!-- backup_plan：{if, action} 折叠行（if 斜体衬线 + action 正文）；旧数据 {name/title} 无 action，退化为静态行 -->
    <template v-if="backupRules.length">
      <details v-for="(r, i) in foldRules" :key="`f${i}`" class="narr-backup">
        <summary>
          <span class="backup-tag">备选</span>
          <em class="backup-if">若{{ ruleIf(r) }}</em>
        </summary>
        <p class="backup-action">{{ r.action }}</p>
      </details>
      <p v-for="(r, i) in staticRules" :key="`s${i}`" class="narr-backup is-static">
        <span class="backup-tag">备选</span>
        <em class="backup-if">{{ r.name || r.title }}</em>
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BackupPlanEntry, DayPlan, PhotoSpotEntry } from '../../types/itinerary'

// 每日叙事区（M4-②b §5.3.2）：theme / note / practical_notes / photo_spots / backup_plan
// 纯展示组件，无 emits；各字段独立空态静默（该行不渲染，不出现空标签）。
const props = defineProps<{
  day: DayPlan
}>()

const practicalNotes = computed(() => (props.day.practicalNotes || []).map((n) => n.trim()).filter(Boolean))

const photoSpots = computed(() =>
  (props.day.photoSpots || []).filter((s) => (s.name || s.title || '').trim()),
)

const backupRules = computed(() =>
  (props.day.backupPlan || []).filter(
    (r) => (r.if || r.name || r.title || '').trim() || (r.action || '').trim(),
  ),
)

/** 新契约条目（有 action）：details/summary 折叠行 */
const foldRules = computed(() => backupRules.value.filter((r) => (r.action || '').trim()))

/** 旧数据条目（无 action）：静态行，不再提供空折叠 */
const staticRules = computed(() => backupRules.value.filter((r) => !(r.action || '').trim()))

function spotName(s: PhotoSpotEntry) {
  return (s.name || s.title || '').trim()
}

function ruleIf(r: BackupPlanEntry) {
  return (r.if || '').trim()
}

const hasNarrative = computed(
  () =>
    !!(props.day.note || '').trim() ||
    practicalNotes.value.length > 0 ||
    photoSpots.value.length > 0 ||
    backupRules.value.length > 0,
)
</script>

<style scoped>
.day-narrative {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  margin: 4px 0 16px;
}

/* ---------- note：本章导语正文 ---------- */
.narr-note {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--lp-ink-soft);
}

/* ---------- practical_notes：callout 容器 + 左 3px 渐变竖线 ---------- */
.narr-callout {
  position: relative;
  margin: 0;
  padding: 10px 14px 10px 16px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--lp-note-callout);
  border-radius: 0 8px 8px 0;
}

.narr-callout::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background-image: var(--lp-theme-accent);
  border-radius: 2px 0 0 2px;
}

.narr-callout li {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--lp-ink-soft);
}

.narr-callout li::before {
  content: '·';
  margin-right: 6px;
  font-weight: 700;
  color: var(--lp-why-ink);
}

/* ---------- photo_spots：浅底深字徽标行（陶土橙家族唯一功能化用途） ---------- */
.narr-photos {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.photos-label {
  font-family: var(--lp-font-data);
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--lp-why-ink);
}

.photo-badge {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 3px 8px;
  padding: 5px 10px;
  border-radius: 6px;
  background: var(--lp-photo-badge);
}

.photo-name {
  font-size: 12px;
  font-weight: 600;
  /* #bd6246 加深派生的徽标深字：浅底上对比 6.4:1（AA） */
  color: color-mix(in srgb, var(--lp-accent-warm) 60%, #2a1208);
}

.photo-tip {
  font-size: 11.5px;
  color: var(--lp-ink-soft);
}

.photo-time {
  font-family: var(--lp-font-data);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--lp-accent-warm) 60%, #2a1208);
}

/* ---------- backup_plan：if 斜体衬线 + action 正文，「若…则…」句式 ---------- */
.narr-backup {
  width: 100%;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
  background: var(--lp-surface);
}

.narr-backup summary {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
}

.narr-backup summary::-webkit-details-marker {
  display: none;
}

.narr-backup summary::after {
  content: '▸';
  margin-left: auto;
  font-size: 11px;
  color: var(--lp-why-ink);
  transition: transform 0.2s ease;
}

.narr-backup[open] summary::after {
  transform: rotate(90deg);
}

.backup-tag {
  flex: none;
  font-family: var(--lp-font-data);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--lp-why-ink);
}

.backup-if {
  font-family: var(--lp-font-display);
  font-style: italic;
  font-size: 13px;
  color: var(--lp-ink-soft);
}

.backup-action {
  margin: 0;
  padding: 0 12px 10px 12px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--lp-ink-soft);
}

/* 旧数据（无 action）静态行：不提供空折叠 */
.narr-backup.is-static {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 12px;
}
</style>
