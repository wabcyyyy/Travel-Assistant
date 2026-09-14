import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useItineraryStore } from '../store/itinerary'
import type { TripItem } from '../types/itinerary'
import { isForeignCity } from '../utils/geo'

/**
 * 行程项图片三级降级（M4-②b 自 DayListCard 收敛为 composable，全量重构方案 §5.3.6）：
 * 0=实景图（行程自带/后端检索）→ 1=地图位置图（保底）→ 2=占位块。
 * 没有坐标且没有另一张图片时，/poi-photo 的 404 无法再降级到地图，直接落占位块，
 * 避免空 src 触发重复请求。
 */
export function useItemPhoto() {
  const store = useItineraryStore()
  const { detail } = storeToRefs(store)
  const amapReady = !!import.meta.env.VITE_AMAP_JS_KEY
  const foreign = computed(() => isForeignCity(detail.value?.city ?? ''))
  const imgFailed = ref<Record<number, number>>({})

  function imgLevel(item: TripItem) {
    return imgFailed.value[item.id!] ?? 0
  }

  function imageProxy(url: string) {
    if (!url) return ''
    if (url.startsWith('/') || url.startsWith('data:') || url.startsWith('blob:')) return url
    if (!/^https?:\/\//i.test(url)) return ''
    return `/api/amap/image?url=${encodeURIComponent(url)}`
  }

  function imgSrc(item: TripItem) {
    const isForeign = foreign.value
    if (imgLevel(item) >= 1) {
      // 保底：高德静态地图位置图（国内有 key 时）
      if (item.longitude && item.latitude && amapReady && !isForeign) {
        return `/api/amap/staticmap?location=${item.longitude},${item.latitude}`
      }
      return imageProxy(item.image || item.imageUrl || '')
    }
    // 实景图：行程自带 → 同源代理
    const own = imageProxy(item.image || item.imageUrl || '')
    if (own) return own
    // 海外：skipAmap 代理走 Wikipedia → Commons → 图库名称兜底，避免高德无覆盖超时
    if (isForeign) {
      return `/api/amap/poi-photo?name=${encodeURIComponent(item.poiName)}&city=${encodeURIComponent(detail.value?.city ?? '')}&skipAmap=true`
    }
    if (amapReady) {
      return `/api/amap/poi-photo?name=${encodeURIComponent(item.poiName)}&city=${encodeURIComponent(detail.value?.city ?? '')}`
    }
    if (item.longitude && item.latitude) {
      return `/api/amap/staticmap?location=${item.longitude},${item.latitude}`
    }
    return ''
  }

  function onImgError(item: TripItem) {
    const id = item.id!
    const hasFallback = Boolean(item.longitude && item.latitude)
    imgFailed.value[id] = hasFallback ? (imgFailed.value[id] ?? 0) + 1 : 2
  }

  return { imgLevel, imgSrc, onImgError }
}
