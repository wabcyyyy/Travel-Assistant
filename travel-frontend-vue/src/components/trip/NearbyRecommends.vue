<template>
  <div v-show="open" class="nearby-panel">
    <p class="nearby-title">
      <span>附近推荐</span>
      <span class="nearby-sub">来自知识库的真实近邻</span>
    </p>
    <p v-if="loading" class="nearby-loading">
      正在查找附近…
    </p>
    <ul v-else-if="items.length" class="nearby-list">
      <li v-for="poi in items" :key="poi.name">
        <a :href="searchLink(poi.name)" target="_blank" rel="noopener">
          {{ poi.name }}
        </a>
        <span class="nearby-meta">
          {{ typeLabel(poi.category) }}
          <template v-if="poi.rating != null"> · {{ poi.rating }} 分</template>
          <template v-if="poi.distanceM != null"> · 距此 {{ formatDistance(poi.distanceM) }}</template>
        </span>
      </li>
    </ul>
    <p v-else class="nearby-empty">知识库中暂无该地点附近的推荐</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { getNearbyPois, type NearbyPoi } from '../../api/itinerary'
import { useItineraryStore } from '../../store/itinerary'
import type { TripItem } from '../../types/itinerary'
import { isForeignCity } from '../../utils/geo'

// 附近推荐面板（M4-②b 自 DayListCard 迁出以瘦身）：轻量 GraphRAG 真实近邻。
// open 变化时首次拉取并在组件实例内缓存结果；优先使用行程项自带真实坐标。
const props = defineProps<{
  item: TripItem
  open: boolean
}>()

const store = useItineraryStore()
const { detail } = storeToRefs(store)
const detailForeign = computed(() => isForeignCity(detail.value?.city ?? ''))

const loading = ref(false)
const loaded = ref(false)
const items = ref<NearbyPoi[]>([])

watch(
  () => props.open,
  async (open) => {
    if (!open || loaded.value) return
    loading.value = true
    try {
      const res = await getNearbyPois({
        city: detail.value?.city ?? '',
        name: props.item.poiName,
        latitude: props.item.latitude ?? undefined,
        longitude: props.item.longitude ?? undefined,
        limit: 5,
      })
      items.value = res.data?.items ?? []
    } catch {
      items.value = []
      ElMessage.warning('附近推荐获取失败，请稍后重试')
    } finally {
      loading.value = false
      loaded.value = true
    }
  },
)

function formatDistance(meters: number | null) {
  if (meters == null) return ''
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)}km` : `${meters}m`
}

function searchLink(name: string) {
  const keyword = `${detail.value?.city ?? ''}${name}`
  if (detailForeign.value) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(keyword)}`
  }
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(keyword)}`
}

const TYPE_LABEL: Record<string, string> = {
  attraction: '景点',
  food: '美食',
  hotel: '酒店',
  transport: '交通',
}

function typeLabel(type: string) {
  return TYPE_LABEL[type] || type
}
</script>

<style scoped>
.nearby-panel {
  margin-top: 8px;
  padding: 8px 12px;
  border: 1px solid var(--lp-border);
  border-radius: 8px;
  background: var(--lp-sand);
}

.nearby-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--lp-ink);
}

.nearby-sub {
  font-weight: 400;
  color: var(--lp-muted);
}

.nearby-loading,
.nearby-empty {
  margin: 0;
  font-size: 12px;
  color: var(--lp-muted);
}

.nearby-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nearby-list li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.nearby-list a {
  color: var(--lp-accent);
  text-decoration: none;
}

.nearby-list a:hover {
  color: var(--lp-accent-hover);
  text-decoration: underline;
}

.nearby-meta {
  color: var(--lp-muted);
}
</style>
