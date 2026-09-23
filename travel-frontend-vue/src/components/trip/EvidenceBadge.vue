<template>
  <span v-if="label" class="evidence-badge" :class="{ sourced }" :title="hint">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TripItem } from '../../types/itinerary'
import { evidenceLabel } from '../../utils/evidence'
const props = defineProps<{ item: TripItem }>()
const label = computed(() => evidenceLabel(props.item))
const sourced = computed(() => ['地点有来源', '部分信息有据'].includes(label.value))
const hint = computed(() => `${props.item.source ? `来源：${props.item.source}。` : ''}仅说明地点参考信息，不代表票价或营业时间已核实。`)
</script>

<style scoped>
.evidence-badge {
  display: inline-block;
  color: var(--lp-text-muted);
  border: 1px solid var(--lp-border);
  border-radius: var(--lp-radius-xs);
  padding: 1px 5px;
  font-size: 11px;
  line-height: 1.5;
}
.sourced { color: var(--lp-accent); }
</style>
