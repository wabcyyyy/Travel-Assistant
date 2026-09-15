<template>
  <div class="app-number" :class="[`size-${size}`, { 'is-disabled': disabled }]">
    <input
      ref="inputEl"
      class="number-el"
      type="number"
      inputmode="decimal"
      :value="display"
      :min="min"
      :max="max"
      :step="step"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-label="ariaLabel || undefined"
      v-bind="$attrs"
      @input="onInput"
      @blur="onBlur"
    />
    <span v-if="suffix" class="number-suffix">{{ suffix }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

// 自研数字输入（v2.6 §19.2，替换 el-input-number）：空值 = null；
// 输入中不夹紧（会打断打字），失焦时按 min/max 夹紧并应用 precision 舍入。
defineOptions({ inheritAttrs: false })
const model = defineModel<number | null>({ default: null })
const props = withDefaults(
  defineProps<{
    min?: number
    max?: number
    step?: number
    precision?: number
    placeholder?: string
    disabled?: boolean
    size?: 'md' | 'sm'
    suffix?: string
    ariaLabel?: string
  }>(),
  { step: 1, placeholder: '', disabled: false, size: 'md', suffix: '', ariaLabel: '' },
)

const inputEl = ref<HTMLInputElement | null>(null)

// 展示值：null → 空串；number → 字符串
const display = computed(() => (model.value == null ? '' : String(model.value)))

function onInput(event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  if (raw === '') {
    model.value = null
    return
  }
  const parsed = Number(raw)
  model.value = Number.isFinite(parsed) ? parsed : null
}

function onBlur(): void {
  if (model.value == null) return
  let next = model.value
  if (props.min != null) next = Math.max(props.min, next)
  if (props.max != null) next = Math.min(props.max, next)
  if (props.precision != null) {
    const factor = 10 ** props.precision
    next = Math.round(next * factor) / factor
  }
  model.value = next
}

defineExpose({ focus: () => inputEl.value?.focus() })
</script>

<style scoped>
.app-number {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  padding: 0 12px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-input);
  background: var(--lp-surface-input);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.app-number:focus-within {
  border-color: var(--lp-accent);
  box-shadow: 0 0 0 3px var(--lp-accent-subtle);
}

.app-number.is-disabled {
  background: var(--lp-surface-2);
  cursor: not-allowed;
}

.number-el {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--lp-text-1);
  font-family: inherit;
  font-variant-numeric: tabular-nums;
}

.number-el::placeholder {
  color: var(--lp-text-muted);
}

.number-suffix {
  color: var(--lp-text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.size-md .number-el {
  height: 36px;
  font-size: var(--lp-text-body);
}

.size-sm .number-el {
  height: 28px;
  font-size: 13px;
}

.number-el:disabled {
  color: var(--lp-text-faint);
}
</style>
