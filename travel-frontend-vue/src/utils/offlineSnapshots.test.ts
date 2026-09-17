/** 离线快照存储测试（C2.5）：内存 IDB 模拟，断言账号隔离/TTL/上限/清理语义。 */

import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearUserSnapshots,
  deleteSnapshot,
  DETAIL_TTL_MS,
  loadSnapshot,
  MAX_DETAIL_SNAPSHOTS,
  saveDetailSnapshot,
  saveListSnapshot,
  setIdbFactory,
  snapshotKeyForDetail,
} from './offlineSnapshots'

/** 最小 IDB 内存实现：只覆盖 offlineSnapshots 用到的 open/get/put/delete/getAll。
 *  request 的 onsuccess 在下一个微任务触发——与真实 IDB 的异步时序一致
 *  （实现先 open() 后挂 handler，同步触发会永远没人应答）。 */
function memoryIdb() {
  const store = new Map<string, unknown>()
  function req<T>(result: T) {
    const request = { result, onsuccess: null as (() => void) | null, onerror: null as (() => void) | null }
    queueMicrotask(() => request.onsuccess?.())
    return request
  }
  const storeOps = {
    get: (key: string) => req(store.has(key) ? store.get(key) : undefined),
    put: (value: unknown) => {
      store.set((value as { key: string }).key, value)
      return req(undefined)
    },
    delete: (key: string) => {
      store.delete(key)
      return req(undefined)
    },
    getAll: () => req([...store.values()] as unknown[]),
  }
  return {
    store,
    open: () => {
      const request = {
        result: {
          createObjectStore: () => undefined,
          transaction: () => ({ objectStore: () => storeOps }),
        },
        onsuccess: null as (() => void) | null,
        onerror: null as (() => void) | null,
        onupgradeneeded: null,
      }
      queueMicrotask(() => request.onsuccess?.())
      return request
    },
  }
}

beforeEach(() => {
  setIdbFactory(memoryIdb())
})

describe('offlineSnapshots', () => {
  it('保存后可按 key 读回；未保存返回 null', async () => {
    await saveDetailSnapshot('alice', 42, { id: 42, title: '杭州' })
    const entry = await loadSnapshot(snapshotKeyForDetail('alice', 42))
    expect(entry).not.toBeNull()
    expect((entry!.payload as { title: string }).title).toBe('杭州')
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 99))).toBeNull()
  })

  it('账号隔离：bob 读不到 alice 的快照，清理互不影响', async () => {
    await saveDetailSnapshot('alice', 42, { owner: 'alice' })
    await saveDetailSnapshot('bob', 42, { owner: 'bob' })

    expect((await loadSnapshot(snapshotKeyForDetail('alice', 42)))!.payload).toEqual({ owner: 'alice' })

    await clearUserSnapshots('alice')
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 42))).toBeNull()
    expect((await loadSnapshot(snapshotKeyForDetail('bob', 42)))!.payload).toEqual({ owner: 'bob' })
  })

  it('过期快照按不存在处理（TTL 7 天）', async () => {
    await saveDetailSnapshot('alice', 42, { stale: true })
    // 直接把 savedAt 拨回 8 天前
    const factoryLike = memoryIdb()
    factoryLike.store.set('alice:detail:42', {
      key: 'alice:detail:42',
      kind: 'detail',
      username: 'alice',
      savedAt: Date.now() - DETAIL_TTL_MS - 1,
      payload: { stale: true },
    })
    setIdbFactory(factoryLike)
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 42))).toBeNull()
  })

  it('详情上限 20 份：最旧的被淘汰，列表快照不受上限影响', async () => {
    for (let tripId = 1; tripId <= MAX_DETAIL_SNAPSHOTS + 3; tripId += 1) {
      await saveDetailSnapshot('alice', tripId, { tripId })
      await new Promise((resolve) => setTimeout(resolve, 1)) // 保证 savedAt 严格递增，淘汰顺序确定
    }
    // 最旧的 1/2/3 被挤出
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 1))).toBeNull()
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 2))).toBeNull()
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 3))).toBeNull()
    // 最新 20 份保留
    expect((await loadSnapshot(snapshotKeyForDetail('alice', 4)))!.payload).toEqual({ tripId: 4 })

    await saveListSnapshot('alice', [{ id: 1 }])
    expect(((await loadSnapshot('alice:list'))!.payload as { id: number }[])[0].id).toBe(1)
  })

  it('删除单份快照：行程删除/鉴权失效后不再回退', async () => {
    await saveDetailSnapshot('alice', 42, { id: 42 })
    await deleteSnapshot(snapshotKeyForDetail('alice', 42))
    expect(await loadSnapshot(snapshotKeyForDetail('alice', 42))).toBeNull()
  })

  it('存储不可用（隐私模式/配额满）时全部静默降级为 null', async () => {
    setIdbFactory(undefined)
    const holder = globalThis as { indexedDB?: unknown }
    const originalIdb = holder.indexedDB
    holder.indexedDB = undefined
    try {
      await saveDetailSnapshot('alice', 42, { id: 42 })
      expect(await loadSnapshot(snapshotKeyForDetail('alice', 42))).toBeNull()
      await clearUserSnapshots('alice') // 不得抛错
    } finally {
      holder.indexedDB = originalIdb
      setIdbFactory(undefined) // 还原默认工厂
    }
  })
})
