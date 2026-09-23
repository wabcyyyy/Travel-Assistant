<template>
  <section class="budget-strip" :class="{ 'is-docked': docked }" aria-label="预算概览">
    <div class="strip-total">
      <span class="strip-label">预估总价</span>
      <span class="strip-amount" :class="{ over: overBudget }">￥{{ fmt(totalAmount) }}</span>
      <span v-if="budgetLimit" class="strip-limit">
        <el-tag :type="overBudget ? 'danger' : 'success'" size="small">
          {{ overBudget ? '超预算' : '预算内' }}
        </el-tag>
        <span class="limit-num">上限 ￥{{ fmt(budgetLimit) }}</span>
      </span>
    </div>

    <div class="strip-cats" aria-label="分类构成">
      <span v-for="row in budgetList" :key="row.category" class="cat">
        <span class="cat-name">{{ row.category }}</span>
        <span class="cat-amount">￥{{ fmt(row.amount) }}</span>
      </span>
    </div>

    <el-popover placement="bottom-end" :width="300" trigger="click">
      <template #reference>
        <button type="button" class="strip-detail">明细</button>
      </template>
      <div class="detail-body">
        <div v-for="row in budgetList" :key="row.category" class="detail-row">
          <span>{{ row.category }}<i v-if="row.itemCount" class="detail-count">×{{ row.itemCount }}</i></span>
          <span class="detail-amount">￥{{ fmt(row.amount) }}</span>
        </div>
        <div class="detail-row is-total">
          <span>合计</span>
          <span class="detail-amount">￥{{ fmt(totalAmount) }}</span>
        </div>
        <p v-if="transportAmount > 0" class="detail-note">
          交通为预估：按城市交通系数 × {{ days }} 天 × {{ persons }} 人估算，未对应具体行程条目。
        </p>
        <p class="detail-note">价格均为人民币估算，请以现场或官方渠道为准。</p>
      </div>
    </el-popover>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { BudgetRow } from '../../types/itinerary'

// 预算概览条（替代原右栏 BudgetPanel 看板）：总价 + 分类 + 状态一行收纳，
// 天级小计移到日卡标题（DayListCard），条目级价格留在点位卡上，全页零重复。
// docked（v2.6 §19.3）：停靠左栏底部时的折叠态——总价一行 + 明细弹层，分类行收起。
const props = withDefaults(
  defineProps<{
    budgetList: BudgetRow[]
    totalAmount: number
    budgetLimit?: number | null
    persons: number
    days: number
    docked?: boolean
  }>(),
  { docked: false },
)

const overBudget = computed(() => {
  if (!props.budgetLimit) return false
  return props.totalAmount > props.budgetLimit
})

/** 交通预估（按城市系数估算，不对应具体条目）：明细弹层里单独说明 */
const transportAmount = computed(() => {
  const row = props.budgetList.find((r) => r.category === '交通')
  return row ? Number(row.amount) || 0 : 0
})

function fmt(value: number | null | undefined) {
  return Number(value ?? 0).toLocaleString('zh-CN')
}
</script>

<style scoped>
.budget-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 28px;
  padding: 14px 22px;
  background: var(--lp-surface-card);
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  margin-bottom: 16px;
}

/* 停靠态（左栏底部）：总价一行 + 明细弹层；分类构成只在明细里看 */
.budget-strip.is-docked {
  gap: 8px 16px;
  padding: 12px 14px;
  border-radius: var(--lp-radius-sm);
  margin-bottom: 0;
}

.budget-strip.is-docked .strip-cats {
  display: none;
}

.budget-strip.is-docked .strip-amount {
  font-size: 20px;
}

/* 总价区：衬线大数字承接手册封面语言 */
.strip-total {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.strip-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--lp-text-muted);
}

.strip-amount {
  font-family: var(--lp-font-display);
  font-weight: 600;
  font-size: 28px;
  line-height: 1.05;
  letter-spacing: -0.03em;
  color: var(--lp-text-1);
  font-variant-numeric: tabular-nums;
}

.strip-amount.over {
  color: var(--lp-danger);
}

.strip-limit {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 4px;
}

.limit-num {
  font-size: 12px;
  color: var(--lp-muted);
  font-variant-numeric: tabular-nums;
}

/* 分类区：纯文字数字对，去掉旧圆点/饼图 */
.strip-cats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 22px;
  min-width: 0;
}

.cat {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}

.cat-name {
  font-size: 12.5px;
  color: var(--lp-muted);
}

.cat-amount {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--lp-ink-soft);
  font-variant-numeric: tabular-nums;
}

/* 明细入口 + 弹层 */
.strip-detail {
  margin-left: auto;
  padding: 3px 12px;
  border: 1px solid var(--lp-border);
  border-radius: 999px;
  background: transparent;
  font-size: 12px;
  color: var(--lp-ink-soft);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.strip-detail:hover {
  color: var(--lp-accent);
  border-color: var(--lp-accent);
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 13px;
  color: var(--lp-ink-soft);
}

.detail-count {
  font-style: normal;
  margin-left: 4px;
  font-size: 11.5px;
  color: var(--lp-muted);
}

.detail-row.is-total {
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--lp-rule);
  font-weight: 700;
  color: var(--lp-ink);
}

.detail-amount {
  font-variant-numeric: tabular-nums;
}

.detail-note {
  margin: 6px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--lp-muted);
}

/* 窄屏：分类行让位给明细弹层，只留总价 + 状态 + 入口 */
@media (max-width: 640px) {
  .budget-strip { gap: 8px 16px; padding: 12px 16px; }
  .strip-cats { display: none; }
  .strip-detail { margin-left: 0; }
}
</style>
