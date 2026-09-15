import { storeToRefs } from 'pinia'

import { searchLocalPois, type LocalPoi } from '../api/pois'
import { useItineraryStore } from '../store/itinerary'
import { useItineraryActions } from './useItineraryActions'
import { toast } from '../components/ui/toast'

// 发现类条目的共享写入口（v2.6 W2）：右栏「排入」与左栏「拖拽入天」共用，
// 避免两处各自拼 payload；itemType 白名单映射与「缺坐标先查本地库补齐」口径保持同源。
interface DiscoverAddable {
  name: string
  category: string
  address?: string | null
  latitude?: number | null
  longitude?: number | null
  poiId?: string | null
  estimatedCost?: number | null
  needReservation?: boolean
}

export function useDiscoverAdd() {
  const store = useItineraryStore()
  const { detail } = storeToRefs(store)
  const actions = useItineraryActions()

  function itemTypeOf(raw: string): string {
    // itemType 白名单仅 attraction/food/hotel/transport：其余（含伴手礼/体验）按游玩点归 attraction
    if (raw === 'food') return 'food'
    if (raw === 'hotel') return 'hotel'
    return 'attraction'
  }

  /** 备选/近邻条目排入某天：缺坐标先查本地知识库补齐；检索失败不阻断加入（坐标留空） */
  async function addSuggestionToDay(s: DiscoverAddable, dayId: number): Promise<void> {
    let latitude = s.latitude ?? undefined
    let longitude = s.longitude ?? undefined
    let address = s.address || undefined
    if (latitude == null || longitude == null) {
      try {
        const res = await searchLocalPois(detail.value?.city ?? '', s.name)
        const hit = (res.data.items || []).find((poi) => poi.latitude != null && poi.longitude != null)
        if (hit) {
          latitude = hit.latitude ?? undefined
          longitude = hit.longitude ?? undefined
          address = address || hit.address || undefined
        }
      } catch {
        // 补坐标失败时按原样加入
      }
    }
    await actions.addItem(detail.value!.id, {
      dayId,
      itemType: itemTypeOf(s.category),
      poiName: s.name,
      poiId: s.poiId || undefined,
      address,
      latitude,
      longitude,
      cost: s.estimatedCost ?? undefined,
    })
    toast.success(
      s.needReservation
        ? `已排入行程：${s.name}（该地点通常需要提前预约）`
        : `已排入行程：${s.name}`,
    )
  }

  /** 本地知识库检索结果排入某天（坐标自带） */
  async function addPoiToDay(poi: LocalPoi, dayId: number): Promise<void> {
    await actions.addItem(detail.value!.id, {
      dayId,
      itemType: itemTypeOf(poi.category),
      poiName: poi.name,
      poiId: String(poi.id),
      address: poi.address || undefined,
      latitude: poi.latitude ?? undefined,
      longitude: poi.longitude ?? undefined,
      cost: poi.cost ?? undefined,
    })
    toast.success(`已排入行程：${poi.name}`)
  }

  return { addSuggestionToDay, addPoiToDay, itemTypeOf }
}
