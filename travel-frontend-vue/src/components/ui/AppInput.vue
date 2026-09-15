<template>
  <div class="app-input" :class="[`size-${size}`, { 'is-disabled': disabled }]">
    <span v-if="$slots.prefix" class="input-prefix"><slot name="prefix" /></span>
    <input
      ref="inputEl"
      class="input-el"
      :type="type"
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-label="ariaLabel || undefined"
      v-bind="$attrs"
      @input="onInput"
      @keydown.enter="emit('enter')"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

// 自研文本输入（v2.6 §19.2，替换 el-input）：单行；尺寸两档；前缀插槽；
// 占位色用 --lp-text-muted（AA 对比），聚焦环与禁用态全走令牌。
defineOptions({ inheritAttrs: false })
const model = defineModel<string>({ default: '' })
withDefaults(
  defineProps<{
    type?: string
    placeholder?: string
    disabled?: boolean
    size?: 'md' | 'sm'
    ariaLabel?: string
  }>(),
  { type: 'text', placeholder: '', disabled: false, size: 'md', ariaLabel: '' },
)
const emit = defineEmits<{ enter: [] }>()

const inputEl = ref<HTMLInputElement | null>(null)

function onInput(event: Event): void {
  model.value = (event.target as HTMLInputElement).value
}

defineExpose({ focus: () => inputEl.value?.focus() })
</script>

<style scoped>
.app-input {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  padding: 0 12px;
  border: 1px solid var(--lp-edge-2);
  border-radius: var(--lp-radius-input);
  background: var(--lp-surface-input);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.app-input:focus-within {
  border-color: var(--lp-accent);
  box-shadow: 0 0 0 3px var(--lp-accent-subtle);
}

.app-input.is-disabled {
  background: var(--lp-surface-2);
  cursor: not-allowed;
}

.input-prefix {
  display: inline-flex;
  align-items: center;
  color: var(--lp-text-muted);
}

.input-el {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--lp-text-1);
  font-family: inherit;
}

.input-el::placeholder {
  color: var(--lp-text-muted);
}

.size-md .input-el {
  height: 36px;
  font-size: var(--lp-text-body);
}

.size-sm .input-el {
  height: 28px;
  font-size: 13px;
}

.input-el:disabled {
  color: var(--lp-text-faint);
}
</style>
