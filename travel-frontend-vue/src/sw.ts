/**
 * Service Worker（C2.5）：只负责「应用壳」——precache 构建产物 + 导航请求离线回退壳。
 *
 * 刻意**不做任何 /api 运行时缓存**：行程/账单是私有数据，私有一致性交由
 * `src/utils/offlineSnapshots.ts` 的按账号 IndexedDB 快照（只存成功读取的本人
 * 列表/详情、7 天 TTL、20 个上限、登出清理），Service Worker 一律直连网络。
 * 这样缓存的错误响应/写请求/他人数据没有任何路径进入磁盘。
 */

/// <reference lib="webworker" />
import { clientsClaim } from 'workbox-core'
import { precacheAndRoute, createHandlerBoundToURL } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'

declare const self: ServiceWorkerGlobalScope

// vite-plugin-pwa injectManifest：构建期把产物清单注入 self.__WB_MANIFEST
precacheAndRoute(self.__WB_MANIFEST)

// 离线导航（刷新/直接打开）一律回应用壳；路由由前端接管（离线快照条幅在页面层）
registerRoute(new NavigationRoute(createHandlerBoundToURL('index.html')))

self.skipWaiting()
clientsClaim()
