import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useItineraryStore } from '../store/itinerary'
import type { TripItem } from '../types/itinerary'

/**
 * 行程项图片三级降级（去高德后重定义）：
 * 0=行程自带/服务端落盘图（同源代理）→ 1=POI 实景图（维基/图库代理）
 * → 2=本地占位块。
 *
 * 高德静态位置图这一级已移除（2026-09-15 去高德）：位置图既消耗配额又
 * 与实景图观感错位；没有图时如实落到占位块，比一张错位的地图截图更诚实。
 */
export function useItemPhoto() {
  const store = useItineraryStore()
  const { detail } = storeToRefs(store)
  const imgFailed = ref<Record<number, number>>({})

  function imgLevel(item: TripItem) {
    return imgFailed.value[item.id!] ?? 0
  }

  function imageProxy(url: string) {
    if (!url) return ''
    if (url.startsWith('/') || url.startsWith('data:') || url.startsWith('blob:')) return url
    if (!/^https?:\/\//i.test(url)) return ''
    return `/api/image-proxy?url=${encodeURIComponent(url)}`
  }

  function poiPhotoUrl(item: TripItem) {
    const name = encodeURIComponent(item.poiName)
    const city = encodeURIComponent(detail.value?.city ?? '')
    return `/api/poi-photo?name=${name}&city=${city}`
  }

  function imgSrc(item: TripItem) {
    const level = imgLevel(item)
    if (level >= 2) return ''
    if (level === 0) {
      const own = imageProxy(item.image || item.imageUrl || '')
      if (own) return own
    }
    return poiPhotoUrl(item)
  }

  function onImgError(item: TripItem) {
    const id = item.id!
    const current = imgFailed.value[id] ?? 0
    // 0→1 只在「有自带图可退」时成立：没有自带图时 0/1 两档是同一个 POI 实景图 URL，
    // 重试既不换 src 也不会再触发 error —— 直接落占位块（v2.7 R3 修：坏图图标挂着不退）
    const hasOwn = Boolean(imageProxy(item.image || item.imageUrl || ''))
    imgFailed.value[id] = current === 0 && hasOwn ? 1 : 2
  }

  return { imgLevel, imgSrc, onImgError }
}
