<template>
  <div ref="mapContainer" class="map-container"></div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { loadAmap } from '../utils/amap'

const props = withDefaults(
  defineProps<{
    center?: [number, number]
    zoom?: number
  }>(),
  {
    center: () => [116.4074, 39.9042] as [number, number],
    zoom: 12,
  }
)

const emit = defineEmits<{ (e: 'ready', map: unknown): void }>()

const mapContainer = ref<HTMLDivElement>()
let mapInstance: { destroy: () => void } | null = null

onMounted(async () => {
  try {
    const AMap = (await loadAmap()) as any
    const [lng, lat] = props.center
    mapInstance = new AMap.Map(mapContainer.value, {
      center: [lng, lat],
      zoom: props.zoom,
    })
    emit('ready', mapInstance)
  } catch (err) {
    console.error('地图加载失败:', err)
  }
})

onBeforeUnmount(() => {
  if (mapInstance) {
    mapInstance.destroy()
    mapInstance = null
  }
})
</script>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  min-height: 300px;
}
</style>