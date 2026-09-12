<template>
  <section v-if="cards.length" class="fork" aria-label="方案分叉">
    <h5 class="fork-title">方案分叉</h5>
    <div class="fork-cards">
      <article v-for="(c, i) in cards" :key="i" class="fork-card" :class="i % 2 === 0 ? 'is-a' : 'is-b'">
        <header class="fork-head">
          <span class="fork-badge">{{ c.badge }}</span>
          <span v-if="c.name" class="fork-name">{{ c.name }}</span>
        </header>
        <p v-if="c.opt.summary" class="fork-summary">{{ c.opt.summary }}</p>
        <!-- tradeoff 拆「+ / −」得失行；无标记的整串作单行说明，不硬拆 -->
        <ul v-if="c.lines.length" class="fork-trade">
          <li v-for="(t, j) in c.lines" :key="j" :class="t.kind">
            <span v-if="t.kind !== 'plain'" class="t-mark" aria-hidden="true">{{ t.kind === 'gain' ? '+' : '−' }}</span>
            <span>{{ t.text }}</span>
          </li>
        </ul>
        <!-- items 只读列表：默认折叠，展示「系统已替你想到的分叉」点位；不做切换（P3 延伸） -->
        <details v-if="c.items.length" class="fork-items">
          <summary>展开方案点位（{{ c.items.length }}）</summary>
          <ul>
            <li v-for="(it, k) in c.items" :key="k">
              <span v-if="it.startTime" class="it-time">{{ it.startTime }}</span>
              <span class="it-name">{{ it.poiName }}</span>
            </li>
          </ul>
        </details>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DayOption, TripItem } from '../../types/itinerary'

// 方案分叉区（M4-②b §5.3.4）：day_options 0-2 组并列卡，方案 A/B 以
// --lp-branch-a/b 左 border + label 徽标区分。默认只展示、不切换；
// 与 backup_plan 的分工：此处为行前主动取舍（并列卡），彼处为行中被动应对（折叠行）。
const props = defineProps<{
  options: DayOption[]
}>()

interface TradeLine {
  kind: 'gain' | 'loss' | 'plain'
  text: string
}

interface ForkCard {
  opt: DayOption
  badge: string
  name: string
  lines: TradeLine[]
  items: TripItem[]
}

/** label 形如「方案A·完整圣地」：拆徽标 + 方案名；不匹配时按序号兜底 */
function splitLabel(label: string | null | undefined, index: number): { badge: string; name: string } {
  const raw = (label || '').trim()
  const m = /^方案\s*([ABab])\s*[·:：、\-]\s*(.+)$/.exec(raw)
  if (m) return { badge: `方案 ${m[1].toUpperCase()}`, name: m[2].trim() }
  return { badge: `方案 ${index === 0 ? 'A' : 'B'}`, name: raw }
}

/** tradeoff 按 「+/−」 前缀或换行/分号拆得失行；全部无标记则整串单行，不硬拆 */
function tradeLines(tradeoff: string | null | undefined): TradeLine[] {
  const raw = (tradeoff || '').split(/\n|；|;/).map((s) => s.trim()).filter(Boolean)
  if (!raw.length) return []
  const lines = raw.map<TradeLine>((line) => {
    if (/^[+＋]/.test(line)) return { kind: 'gain', text: line.replace(/^[+＋]\s*/, '') }
    if (/^[-−–]/.test(line)) return { kind: 'loss', text: line.replace(/^[-−–]\s*/, '') }
    return { kind: 'plain', text: line }
  })
  return lines.every((t) => t.kind === 'plain') ? [{ kind: 'plain', text: raw.join('；') }] : lines
}

const cards = computed<ForkCard[]>(() =>
  props.options
    .filter((o) => (o.label || o.summary || o.tradeoff || '').trim())
    .map((opt, i) => ({
      opt,
      ...splitLabel(opt.label, i),
      lines: tradeLines(opt.tradeoff),
      items: (opt.items || []).filter((it) => !!it.poiName),
    })),
)
</script>

<style scoped>
.fork {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--lp-rule);
}

.fork-title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--lp-ink);
}

.fork-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

/* 左 border + 徽标取 --lp-branch-a/b（叙事层，避开操作色） */
.fork-card {
  padding: 12px 14px;
  background: var(--lp-surface);
  border: 1px solid var(--lp-border);
  border-left: 3px solid var(--lp-branch-a);
  border-radius: 0 10px 10px 0;
}

.fork-card.is-b {
  border-left-color: var(--lp-branch-b);
}

.fork-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.fork-badge {
  flex: none;
  padding: 2px 9px;
  border-radius: 999px;
  font-family: var(--lp-font-data);
  font-size: 11px;
  font-weight: 700;
  background: color-mix(in srgb, var(--lp-branch-a) 10%, #fff);
  color: var(--lp-branch-a);
}

.is-b .fork-badge {
  background: color-mix(in srgb, var(--lp-branch-b) 10%, #fff);
  color: var(--lp-branch-b);
}

.fork-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--lp-ink);
}

.fork-summary {
  margin: 0 0 6px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--lp-ink-soft);
}

.fork-trade {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.fork-trade li {
  display: flex;
  gap: 6px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--lp-ink-soft);
  font-variant-numeric: tabular-nums;
}

.t-mark {
  flex: none;
  font-family: var(--lp-font-data);
  font-weight: 700;
}

.is-a .t-mark {
  color: var(--lp-branch-a);
}

.is-b .t-mark {
  color: var(--lp-branch-b);
}

.fork-items {
  margin-top: 8px;
}

.fork-items summary {
  padding: 2px 0;
  font-size: 12px;
  color: var(--lp-why-ink);
  cursor: pointer;
  list-style: none;
}

.fork-items summary::-webkit-details-marker {
  display: none;
}

.fork-items summary::before {
  content: '▸ ';
}

.fork-items ul {
  margin: 6px 0 0;
  padding: 8px 10px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--lp-sand);
  border-radius: 8px;
}

.fork-items li {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--lp-ink-soft);
}

.it-time {
  flex: none;
  font-family: var(--lp-font-data);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--lp-why-ink);
}
</style>
