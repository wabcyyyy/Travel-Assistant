<template>
  <div class="atlas-sidebar">
    <div
      v-for="pin in pins"
      :id="`city-card-${pin.city}`"
      :key="pin.city"
      class="city-card"
      :class="{ active: pin.city === selectedCity }"
    >
      <button type="button" class="city-main" @click="emit('select', pin.city)">
        <span class="city-line">
          <span class="city-name">{{ pin.city }}</span>
          <Chip :tone="pin.countryCode ? 'accent' : 'warning'">{{ pin.country ?? '未归国' }}</Chip>
          <Chip :tone="pin.coordSource === 'items' ? 'neutral' : 'warning'">
            {{ pin.coordSource === 'items' ? '点位质心' : '字典兜底' }}
          </Chip>
        </span>
        <span class="city-meta">{{ pin.tripCount }} 段旅程</span>
      </button>
      <ul class="trip-list">
        <li v-for="trip in pin.trips" :key="trip.id">
          <button type="button" class="trip-row" @click="emit('open', trip.id)">
            <span class="trip-title">{{ trip.title }}</span>
            <span class="trip-meta">
              {{ trip.startDate ?? '未设置' }} · {{ trip.scope === 'visited' ? '去过' : '计划中' }}
            </span>
            <span class="trip-open">翻开</span>
          </button>
        </li>
      </ul>
    </div>

    <p v-if="!pins.length" class="hint">没有可上图的城市。</p>

    <div v-if="unknownCities.length" class="unknown">
      <p class="unknown-head">未上图城市（{{ unknownCities.length }}）</p>
      <p class="hint">
        <span v-for="entry in unknownCities" :key="entry.city" class="unknown-item">
          {{ entry.city }}<em>{{ entry.reason === 'no_coordinates' ? '缺坐标' : '未归国' }}</em>
        </span>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import Chip from '../ui/Chip.vue'
import type { AtlasPin, AtlasUnknownCity } from '../../types/atlas'

// 图鉴侧栏：城市卡片（钉↔卡片联动的高亮态由 selectedCity 驱动）
defineProps<{
  pins: AtlasPin[]
  unknownCities: AtlasUnknownCity[]
  selectedCity: string | null
}>()

const emit = defineEmits<{
  select: [city: string]
  open: [id: number]
}>()
</script>

<style scoped>
.atlas-sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-2);
}

.city-card {
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-card);
  background: var(--lp-surface-card);
  overflow: hidden;
}

.city-card.active {
  border-color: var(--lp-accent);
  box-shadow: var(--lp-shadow-sm);
}

.city-main {
  display: block;
  width: 100%;
  padding: var(--lp-space-3);
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.city-line {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  flex-wrap: wrap;
}

.city-name {
  font-size: var(--lp-text-subtitle);
  font-weight: 700;
  color: var(--lp-text-1);
}

.city-meta {
  display: block;
  margin-top: 4px;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.trip-list {
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--lp-edge-faint);
}

.trip-row {
  display: flex;
  align-items: center;
  gap: var(--lp-space-2);
  width: 100%;
  padding: var(--lp-space-2) var(--lp-space-3);
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.trip-row:hover {
  background: var(--lp-surface-2);
}

.trip-title {
  font-weight: 600;
  color: var(--lp-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trip-meta {
  margin-left: auto;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
  white-space: nowrap;
}

.trip-open {
  flex: none;
  font-size: var(--lp-text-caption);
  color: var(--lp-accent-hover);
  font-weight: 600;
}

.hint {
  margin: 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.unknown {
  padding: var(--lp-space-2) var(--lp-space-3);
  border: 1px dashed var(--lp-edge-2);
  border-radius: var(--lp-radius-card);
}

.unknown-head {
  margin: 0 0 4px;
  font-size: var(--lp-text-caption);
  font-weight: 700;
  color: var(--lp-warning);
}

.unknown-item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  margin-right: var(--lp-space-3);
}

.unknown-item em {
  font-style: normal;
  color: var(--lp-text-faint);
}
</style>
