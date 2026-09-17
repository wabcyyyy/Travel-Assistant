import {
  addItem,
  applyHotelOption,
  applyPlans,
  deleteItem,
  optimizeDay as optimizeDayApi,
  reorderItems,
  updateDay as updateDayApi,
  updateItem,
} from '../api/itinerary'
import type { ApiResult } from '../api/request'
import { useItineraryStore } from '../store/itinerary'
import type { HotelOption } from '../types/itinerary'
import type { ChatDayPlan } from '../types/chat'
import type { ItineraryDetail, TripItem } from '../types/itinerary'

/** 从未知错误对象中安全读取 HTTP 状态码（axios 错误结构）。 */
export function statusOfError(err: unknown): number | undefined {
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { status?: number } }).response
    return response?.status
  }
  return undefined
}

/** 是否乐观锁冲突（HTTP 409）：需回滚本地状态并对账最新详情。 */
export function isConflictError(err: unknown): boolean {
  return statusOfError(err) === 409
}

/** fetch 流式中止（AbortController 超时）：直接终止，不回退阻塞端点。 */
export function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === 'AbortError'
}

/** axios 取消（超时/abort）：CanceledError / ERR_CANCELED。 */
export function isCanceledError(err: unknown): boolean {
  return err instanceof Error
    && ((err as Error & { code?: string }).code === 'ERR_CANCELED' || err.name === 'CanceledError')
}

/** 读取后端/网络错误的展示文案（拦截器已弹 toast，这里用于对话内回显）。 */
export function errorMessageOf(err: unknown): string | undefined {
  if (err && typeof err === 'object') {
    const e = err as { response?: { data?: { message?: string } }; message?: string }
    return e.response?.data?.message || e.message
  }
  return undefined
}

/**
 * 行程写操作统一入口（M4-① AD7）：
 * 统一「乐观快照（beginOp）→ 调 API → 成功 commitOp + setDetail 落 store /
 * 失败 rollbackOp 回滚」，409 冲突时回滚后全量对账并明确提示。
 * 酒店替换（HotelOptionsDialog）/备选采纳/草稿应用均经此入口。
 */
export function useItineraryActions() {
  const store = useItineraryStore()

  /**
   * 统一写操作管线。成功返回服务端权威详情（调用方无需再手工赋值 detail）；
   * 其余错误（拦截器已提示）回滚后原样上抛，保持各调用点既有 catch 语义。
   */
  async function run(
    label: string,
    task: () => Promise<ApiResult<ItineraryDetail>>,
  ): Promise<ItineraryDetail> {
    const opId = store.beginOp(label)
    try {
      const res = await task()
      store.commitOp(opId)
      store.setDetail(res.data)
      return res.data
    } catch (err) {
      store.rollbackOp(opId)
      if (isConflictError(err)) {
        ElMessage.warning('他人已修改此行程，已为您刷新最新内容')
        await store.reconcile()
      }
      throw err
    }
  }

  return {
    /** 新增行程项（搜索添加 / 备选池「加入行程」采纳均走此入口）。 */
    addItem(id: number | string, data: Partial<TripItem> & { dayId: number }) {
      return run('添加行程项', () => addItem(id, data))
    },
    /** 编辑行程项（时间/费用/标签/备注）。 */
    updateItem(itemId: number, data: Partial<TripItem>) {
      return run('编辑行程项', () => updateItem(itemId, data))
    },
    /** 删除行程项。 */
    deleteItem(itemId: number) {
      return run('删除行程项', () => deleteItem(itemId))
    },
    /** 拖拽排序提交。 */
    reorderItems(id: number | string, dayId: number, itemIds: number[]) {
      return run('调整顺序', () => reorderItems(id, dayId, itemIds))
    },
    /** 跨天移动（S4）：复用既有 updateItem 带 dayId，不新增端点；后端前后各打快照。 */
    moveToDay(itemId: number, dayId: number) {
      return run('移动行程项', () => updateItem(itemId, { dayId }))
    },
    /** 优化某天路线（W3）：后端全量重排 + 前后快照，经统一写管线回填权威详情。 */
    optimizeDay(id: number | string, dayId: number) {
      return run('优化路线', () => optimizeDayApi(id, dayId))
    },
    /** 编辑日副标题（W3）：复用 theme 列，空串清空回退自动标题。 */
    updateDay(id: number | string, dayId: number, theme: string) {
      return run('编辑日标题', () => updateDayApi(id, dayId, theme))
    },
    /** 应用 chat 草稿（「应用到行程」）。 */
    applyPlans(
      id: number | string,
      plans: ChatDayPlan[],
      actionMessageId?: number,
      baseRevision?: string,
    ) {
      return run('应用修改草稿', () => applyPlans(id, plans, actionMessageId, baseRevision))
    },
    /** 替换酒店方案（HotelOptionsDialog「选择此方案」）。 */
    applyHotelOption(
      id: number | string,
      option: Pick<HotelOption, 'hotelName' | 'tier'>,
      roomType: string,
      dayNos: number[],
      actionMessageId?: number,
      baseRevision?: string,
    ) {
      return run('替换酒店', () =>
        applyHotelOption(id, option, roomType, dayNos, actionMessageId, baseRevision))
    },
  }
}
