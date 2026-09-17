/**
 * 离线快照（C2.5）：按账号隔离的「本人行程」只读缓存。
 *
 * 设计红线（PLAN C2.5）：
 * - 只存**在线成功读取**（HTTP 200 + 业务 code 200）的本人列表/详情；错误响应、
 *   写请求一律不入缓存（快照只在页面层成功回调里写入）。
 * - 键以登录账号（username，库内唯一）隔离：换账号既读不到、也清不到对方数据。
 * - 上限：最近 20 个行程详情、7 天有效期；超限/过期在写入与读取时双向淘汰。
 * - 存储不可用（隐私模式/配额满）时静默降级为「无离线快照」，线上功能不受影响。
 *
 * 存储选 IndexedDB（localStorage 5MB 装不下 20 份行程详情）。测试通过
 * `setIdbFactory` 注入内存实现（vitest 无 IDB），生产默认走 window.indexedDB。
 */

export type SnapshotKind = 'detail' | 'list'

export interface SnapshotEntry<T = unknown> {
  key: string
  kind: SnapshotKind
  username: string
  savedAt: number
  payload: T
}

const DB_NAME = 'ta-offline-snapshots'
const DB_VERSION = 1
const STORE = 'snapshots'
export const DETAIL_TTL_MS = 7 * 24 * 60 * 60 * 1000 // 7 天
export const MAX_DETAIL_SNAPSHOTS = 20 // 最近 20 个自有行程

type IDBFactoryLike = {
  open(name: string, version?: number): IDBOpenDBRequestLike
  deleteDatabase?(name: string): unknown
}

type IDBRequestLike<T = unknown> = { result: T; onsuccess: (() => void) | null; onerror: (() => void) | null }

interface IDBObjectStoreLike {
  get(key: string): IDBRequestLike
  put(value: unknown): IDBRequestLike
  delete(key: string): IDBRequestLike
  getAll(): IDBRequestLike<unknown[]>
}

interface IDBDatabaseLike {
  createObjectStore(name: string): void
  transaction(store: string, mode?: string): { objectStore(name: string): IDBObjectStoreLike }
}

interface IDBOpenDBRequestLike extends IDBRequestLike<IDBDatabaseLike> {
  onupgradeneeded: ((event: { target?: { result?: IDBDatabaseLike } }) => void) | null
}

let idbFactory: IDBFactoryLike | undefined = undefined
let dbPromise: Promise<IDBDatabaseLike | null> | undefined = undefined

/** 测试注入点：传入内存实现的 IDBFactory（或 undefined 还原默认）。 */
export function setIdbFactory(factory: IDBFactoryLike | undefined): void {
  idbFactory = factory
  dbPromise = undefined
}

function factory(): IDBFactoryLike | undefined {
  if (idbFactory !== undefined) return idbFactory
  // 边界收窄：真实 IDBFactory 与本文件的最小接口只做一次 unknown 过桥
  return (globalThis as unknown as { indexedDB?: IDBFactoryLike | undefined }).indexedDB
}

function openDb(): Promise<IDBDatabaseLike | null> {
  const f = factory()
  if (!f) return Promise.resolve(null)
  if (!dbPromise) {
    dbPromise = new Promise((resolve) => {
      let settled = false
      const request = f.open(DB_NAME, DB_VERSION)
      request.onupgradeneeded = (event) => {
        event.target?.result?.createObjectStore(STORE)
      }
      request.onsuccess = () => {
        if (!settled) {
          settled = true
          resolve(request.result)
        }
      }
      request.onerror = () => {
        if (!settled) {
          settled = true
          resolve(null) // 存储不可用：按「无离线能力」降级，绝不抛错打断线上功能
        }
      }
      setTimeout(() => {
        if (!settled) {
          settled = true
          resolve(null)
        }
      }, 2000)
    })
  }
  return dbPromise
}

function requestToPromise<T>(request: IDBRequestLike<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('idb request failed'))
  })
}

function detailKey(username: string, tripId: number | string): string {
  return `${username}:detail:${tripId}`
}

export function snapshotKeyForDetail(username: string, tripId: number | string): string {
  return detailKey(username, tripId)
}

export function snapshotKeyForList(username: string): string {
  return `${username}:list`
}

/** 保存本人行程详情快照；顺带淘汰过期与超上限的旧详情。失败静默。 */
export async function saveDetailSnapshot(username: string, tripId: number | string, payload: unknown): Promise<void> {
  await writeEntry({
    key: detailKey(username, tripId),
    kind: 'detail',
    username,
    savedAt: Date.now(),
    payload,
  })
}

/** 保存本人行程列表快照。失败静默。 */
export async function saveListSnapshot(username: string, payload: unknown): Promise<void> {
  await writeEntry({
    key: snapshotKeyForList(username),
    kind: 'list',
    username,
    savedAt: Date.now(),
    payload,
  })
}

async function writeEntry(entry: SnapshotEntry): Promise<void> {
  try {
    const db = await openDb()
    if (!db) return
    const store = db.transaction(STORE, 'readwrite').objectStore(STORE)
    await requestToPromise(store.put(entry))
    if (entry.kind === 'detail') await prune(usernameOf(entry.key))
  } catch {
    /* 配额满/写失败：停私有离线回退，线上功能不受影响 */
  }
}

function usernameOf(key: string): string {
  return key.slice(0, key.indexOf(':'))
}

/** 淘汰：7 天过期 + 每账号最多 MAX_DETAIL_SNAPSHOTS 份详情（旧详情让位）。 */
async function prune(username: string): Promise<void> {
  const db = await openDb()
  if (!db) return
  const store = db.transaction(STORE, 'readwrite').objectStore(STORE)
  const all = (await requestToPromise(store.getAll())) as SnapshotEntry[]
  const now = Date.now()
  const mine = all.filter((entry) => entry.username === username)
  for (const entry of mine) {
    if (now - entry.savedAt > DETAIL_TTL_MS) await requestToPromise(store.delete(entry.key))
  }
  const survivors = mine
    .filter((entry) => entry.kind === 'detail' && now - entry.savedAt <= DETAIL_TTL_MS)
    .sort((a, b) => b.savedAt - a.savedAt)
  for (const entry of survivors.slice(MAX_DETAIL_SNAPSHOTS)) {
    await requestToPromise(store.delete(entry.key))
  }
}

/** 读取：过期视为不存在（淘汰延迟到下次写入，读路径零成本）。 */
export async function loadSnapshot<T = unknown>(key: string): Promise<SnapshotEntry<T> | null> {
  try {
    const db = await openDb()
    if (!db) return null
    const store = db.transaction(STORE).objectStore(STORE)
    const entry = (await requestToPromise(store.get(key))) as SnapshotEntry<T> | undefined
    if (!entry) return null
    if (Date.now() - entry.savedAt > DETAIL_TTL_MS) return null
    return entry
  } catch {
    return null
  }
}

/** 登出/切换账号：清掉该账号全部快照（其他账号数据不动）。失败静默。 */
export async function clearUserSnapshots(username: string): Promise<void> {
  try {
    const db = await openDb()
    if (!db) return
    const store = db.transaction(STORE, 'readwrite').objectStore(STORE)
    const all = (await requestToPromise(store.getAll())) as SnapshotEntry[]
    for (const entry of all) {
      if (entry.username === username) await requestToPromise(store.delete(entry.key))
    }
  } catch {
    /* 存储不可用即无事可清 */
  }
}

/** 删除单份详情快照（行程被删除/鉴权失效时调用，不回退旧数据）。失败静默。 */
export async function deleteSnapshot(key: string): Promise<void> {
  try {
    const db = await openDb()
    if (!db) return
    const store = db.transaction(STORE, 'readwrite').objectStore(STORE)
    await requestToPromise(store.delete(key))
  } catch {
    /* 同上 */
  }
}
