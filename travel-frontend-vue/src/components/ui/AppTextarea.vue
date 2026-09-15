<template>
  <textarea
    ref="inputEl"
    class="app-textarea"
    :value="model"
    :rows="rows"
    :placeholder="placeholder"
    :disabled="disabled"
    :aria-label="ariaLabel || undefined"
    v-bind="$attrs"
    @input="onInput"
  ></textarea>
</template>

<script setup lang="ts">
import { ref } from 'vue'

// 自研多行输入（v2.6 §19.2，替换 el-input type=textarea）：纵向可拉伸、令牌化外观。
defineOptions({ inheritAttrs: false })
const model = defineModel<string>({ default: '' })
withDefaults(
  defineProps<{
    rows?: number
    placeholder?: string
    disabled?: boolean
    ariaLabel?: string
  }>(),
  { rows: 3, placeholder: '', disabled: false, ariaLabel: '' },
)

const inputEl = ref<HTMLTextAreaElement | null>(null)

function onInput(event: Event): void {
  model.value = (event.target as HTMLTextAreaElement).value
}

defineExpose({ focus: () => inputEl.value?.focus() })
</script>

<style scoped>
.app-textarea {
  display: block;
  width: 100%;
  min-height: 64px;
  padding: 10px 12px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-input);
  background: var(--lp-surface-input);
  color: var(--lp-text-1);
  font-family: inherit;
  font-size: var(--lp-text-body);
  line-height: 1.6;
  resize: vertical;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.app-textarea::placeholder {
  color: var(--lp-text-muted);
}

.app-textarea:focus {
  border-color: var(--lp-accent);
  box-shadow: 0 0 0 3px var(--lp-accent-subtle);
}

.app-textarea:disabled {
  background: var(--lp-surface-2);
  color: var(--lp-text-faint);
  cursor: not-allowed;
}
</style>
