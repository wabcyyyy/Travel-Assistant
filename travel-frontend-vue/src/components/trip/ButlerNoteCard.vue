<template>
  <div class="butler-letter" :class="{ 'is-streaming': streaming }">
    <div class="letter-head">
      <span class="letter-kicker">AI 管家说</span>
      <span class="letter-rule" aria-hidden="true"></span>
    </div>

    <div class="letter-body">
      <!-- 首段衬线首字下沉（::first-letter），正文随流式相位渐进呈现 -->
      <p v-for="(para, i) in letterParas" :key="i" class="letter-para">{{ para }}</p>
    </div>

    <!-- 预约提醒不属于信件正文：独立提示行，避免混入叙事 -->
    <ul v-if="reminders.length" class="letter-reminders">
      <li v-for="(r, i) in reminders" :key="i">{{ r }}</li>
    </ul>

    <p class="letter-sign">你的 AI 管家</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// 「AI 管家说」卡：butler_note 相位以 streaming 驱动淡入
// （reduce 下静态呈现）。信件按段落渲染；【预约提醒】行为系统追加条目，
// 拆出正文单独成行，避免污染叙事与首字下沉。
const props = withDefaults(
  defineProps<{
    /** 管家讲解原文（detail.planNote） */
    note?: string | null
    /** 流式生成中标记（streamState.phase === 'butler' 时由壳传入） */
    streaming?: boolean
  }>(),
  { note: '', streaming: false },
)

const RESERVATION_MARKER = '【预约提醒】'

const letterParas = computed(() => {
  const raw = (props.note || '').replace(/\\n/g, '\n')
  return raw
    .split('\n')
    .map((s) => s.trim())
    .filter((s) => s && !s.startsWith(RESERVATION_MARKER))
})

const reminders = computed(() => {
  const raw = (props.note || '').replace(/\\n/g, '\n')
  return raw
    .split('\n')
    .map((s) => s.trim())
    .filter((s) => s.startsWith(RESERVATION_MARKER))
})
</script>

<style scoped>
/* 暖纸底为管家叙事专属契约：--lp-paper 只用于刊物语段（管家说 / 核查附录） */
.butler-letter {
  margin-bottom: 16px;
  padding: 18px 22px 14px;
  border-left: 3px solid var(--lp-accent-warm);
  border-radius: 0 12px 12px 0;
  background: var(--lp-paper);
}

/* 流式淡入：reduce 下不加动画，直接静态呈现 */
.butler-letter.is-streaming {
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
  .butler-letter.is-streaming {
    animation: none;
  }
}

.letter-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.letter-kicker {
  flex: none;
  font-weight: 800;
  color: var(--lp-accent-warm);
  font-size: 12.5px;
  letter-spacing: 0.14em;
}

.letter-rule {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, rgb(189 98 70 / 35%), rgb(189 98 70 / 0%));
}

/* 正文占满卡宽：窄栏会在宽卡右侧留大片空白；中文两端对齐 + 足够行高保证可读性 */
.letter-body {
  text-align: justify;
}

.letter-para {
  margin: 0 0 10px;
  line-height: 1.9;
  color: var(--lp-ink-soft);
  font-size: 14px;
}

.letter-para:last-child {
  margin-bottom: 0;
}

/* 首段首字下沉：衬线 + 青绿，两行高度（斜体规则不适用，非斜体） */
.letter-para:first-of-type::first-letter {
  float: left;
  font-family: var(--lp-font-display);
  font-weight: 600;
  font-size: 2.7em;
  line-height: 1.05;
  padding: 2px 10px 0 0;
  color: var(--lp-accent);
}

.letter-reminders {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.letter-reminders li {
  padding: 6px 10px;
  border: 1px solid rgb(189 98 70 / 28%);
  border-radius: 8px;
  background: rgb(255 255 255 / 60%);
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--lp-ink-soft);
}

.letter-sign {
  margin: 12px 0 0;
  text-align: right;
  font-family: var(--lp-font-display);
  font-style: italic;
  font-size: 13px;
  color: var(--lp-why-ink);
}
</style>
