import { ref } from 'vue'

import { setArchived } from '../api'
import { toast } from '../components/ui/toast'
import { coverForCity } from '../constants/covers'
import type { ItinerarySummary } from '../types/itinerary'

/**
 * 行程卡/工作台「行操作」的共享逻辑（R5-5）：换封面 / 分享 弹窗态、封面取值、归档。
 * HomeView 与 TripsView 曾逐字复制同一组函数与 ref；这里收敛为单一来源。
 *
 * `reload` 由调用方注入（各自的列表刷新）：封面更新、归档成功后都要重拉列表。
 */
export function useTripRowActions(options: { reload: () => void | Promise<void> }) {
  const coverVisible = ref(false)
  const coverTarget = ref<ItinerarySummary | null>(null)
  const shareVisible = ref(false)
  const shareTarget = ref<ItinerarySummary | null>(null)

  /** 封面优先级：coverUrl（服务端 snapshot）→ 城市兜底图 */
  function coverOf(row: ItinerarySummary): string {
    return row.coverUrl || coverForCity(row.city)
  }

  function openCover(row: ItinerarySummary): void {
    coverTarget.value = row
    coverVisible.value = true
  }

  function openShare(row: ItinerarySummary): void {
    shareTarget.value = row
    shareVisible.value = true
  }

  /** 封面更新后列表卡片要跟着变（封面图在列表上） */
  function onCoverUpdated(): void {
    void options.reload()
  }

  async function archive(row: ItinerarySummary, archived: boolean): Promise<void> {
    try {
      await setArchived(row.id, archived)
      // 自研 toast 而非 ElMessage：ep:lint 允许清单只减不增（v2.6 §19.2）
      toast.success(archived ? '已归档' : '已取消归档')
      void options.reload()
    } catch {
      /* 拦截器已提示 */
    }
  }

  return {
    coverVisible,
    coverTarget,
    shareVisible,
    shareTarget,
    coverOf,
    openCover,
    openShare,
    onCoverUpdated,
    archive,
  }
}
