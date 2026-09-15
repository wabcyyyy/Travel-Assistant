<template>
  <AppSheet
    :model-value="visible"
    :title="title"
    :size="size"
    direction="btt"
    @update:model-value="emit('update:visible', $event)"
  >
    <slot />
  </AppSheet>
</template>

<script setup lang="ts">
import AppSheet from './AppSheet.vue'

// 底部面板（移动端承载侧栏内容）：自研 AppSheet 的 btt 形态（v2.6 §19.2 去 el-drawer）
withDefaults(defineProps<{ visible: boolean; title?: string; size?: string }>(), {
  title: '',
  size: '72%',
})
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()
</script>
