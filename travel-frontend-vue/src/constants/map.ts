import { setWorkerUrl } from 'maplibre-gl'

// worker 是与依赖包同版本的原样拷贝（见 vite.config.ts 的 maplibre-worker-assets 插件）：
// 不显式指定时 SDK 按 import.meta.url 推算 worker 路径，构建/dev 产物里都不存在该文件，
// worker 404 后样式解析永不完成 → 地图静默空白。
setWorkerUrl('/maplibre/maplibre-gl-worker.mjs')

/**
 * 地图栈的单一来源（SPEC §7.4/§7.5；v2.7 §20 R0 换 OpenFreeMap）：详情行程图 / Atlas /
 * 加点工作台共用同一 SDK 与同一底图。
 *
 * OpenFreeMap（免 key 在线矢量瓦片）：无注册、无请求配额、商用允许，**署名是 license 要求**；
 * 只发 MapLibre STYLE 文档（非 {z}/{x}/{y} 模板）。常量照抄 TREK
 * `client/src/constants/mapDefaults.ts`，URL 原样。CARTO 免 key 瓦片自 2026-08 起带
 * 水印、key 需邮件申请，故弃用（与 TREK 同款理由）。
 */
export const OFM_POSITRON = 'https://tiles.openfreemap.org/styles/positron'
export const OFM_DARK = 'https://tiles.openfreemap.org/styles/dark'

/**
 * 底图随外观切换（html.dark 由 styles/appearance.ts 唯一写入）：亮 positron / 暗 dark。
 * 只读不写 DOM——外观契约要求（appearance.ts 注释），这里仅按当前 class 取值。
 */
export function basemapUrlForScheme(): string {
  return document.documentElement.classList.contains('dark') ? OFM_DARK : OFM_POSITRON
}
