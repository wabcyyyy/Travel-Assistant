<template>
  <section class="tip-card" :class="`kind-${kind}`">
    <span class="tip-icon" aria-hidden="true">
      <component :is="ICONS[kind ?? 'info']" :size="15" />
    </span>
    <div class="tip-body">
      <p class="tip-title">{{ title }}</p>
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
import { Camera, Info, TriangleAlert } from 'lucide-vue-next'

// 内联提示卡（v2.6 §19.3，TREK 式彩色小卡）：左栏日卡流内的就地提示。
// kind 决定基调（info=蓝青 / warn=琥珀 / photo=浅绿），全部消费令牌；内容由消费方插槽组织。
const props = withDefaults(
  defineProps<{ kind?: 'info' | 'warn' | 'photo'; title: string }>(),
  { kind: 'info' },
)

const ICONS: Record<'info' | 'warn' | 'photo', unknown> = {
  info: Info,
  warn: TriangleAlert,
  photo: Camera,
}
void props
</script>

<style scoped>
.tip-card {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--lp-radius-sm);
}

.kind-info {
  background: var(--lp-accent-subtle);
}

.kind-warn {
  background: var(--lp-warning-soft);
}

.kind-photo {
  background: var(--lp-success-soft);
}

.tip-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--lp-surface-card) 78%, transparent);
  color: var(--lp-text-2);
}

.kind-info .tip-icon {
  color: var(--lp-accent-hover);
}

.kind-warn .tip-icon {
  color: var(--lp-warning);
}

.kind-photo .tip-icon {
  color: var(--lp-success);
}

.tip-body {
  flex: 1;
  min-width: 0;
}

.tip-title {
  margin: 0 0 4px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--lp-text-1);
}
</style>
