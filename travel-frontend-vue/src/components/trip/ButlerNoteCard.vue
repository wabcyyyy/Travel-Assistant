<template>
  <div class="butler-strip" :class="{ 'is-streaming': streaming }">
    <div class="butler-head">AI 管家说</div>
    <p class="butler-text">{{ text }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// 管家讲解卡（M4-②a §5.4 迁出 / M4-②b §5.3.5 激活）：butler_note 相位以 streaming
// 驱动淡入（reduce 下静态呈现，无动画）。
const props = withDefaults(
  defineProps<{
    /** 管家讲解原文（detail.planNote） */
    note?: string | null
    /** 流式生成中标记（streamState.phase === 'butler' 时由壳传入） */
    streaming?: boolean
  }>(),
  { note: '', streaming: false },
)

// 把历史数据里字面的 "\n" 还原为真实换行（与拆分前 butlerNote 计算一致）
const text = computed(() => (props.note || '').replace(/\\n/g, '\n'))
</script>

<style scoped>
.butler-strip {
  margin-bottom: 16px;
  padding: 12px 16px;
  border-left: 3px solid var(--lp-accent-warm);
  border-radius: 0 8px 8px 0;
  background: var(--lp-paper);
}

/* 流式淡入：reduce 下不加动画，直接静态呈现 */
.butler-strip.is-streaming {
  animation: butler-fade-in 0.45s ease both;
}

@keyframes butler-fade-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .butler-strip.is-streaming {
    animation: none;
  }
}

.butler-head {
  font-weight: 800;
  margin-bottom: 6px;
  color: var(--lp-ink);
  font-size: 13px;
  letter-spacing: 0.04em;
}

.butler-text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.75;
  color: var(--lp-ink-soft);
  font-size: 14px;
}
</style>
