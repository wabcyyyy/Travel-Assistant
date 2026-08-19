import AMapLoader from '@amap/amap-jsapi-loader'

let cachedAmap: unknown = null

export function loadAmap(): Promise<unknown> {
  if (cachedAmap) {
    return Promise.resolve(cachedAmap)
  }
  const key = import.meta.env.VITE_AMAP_JS_KEY
  if (!key) {
    return Promise.reject(new Error('缺少 VITE_AMAP_JS_KEY，请在 .env 中配置高德 JS key'))
  }
  return AMapLoader.load({
    key,
    securityJsCode: import.meta.env.VITE_AMAP_SECURITY_CODE,
    version: '2.0',
    plugins: ['AMap.Scale', 'AMap.ToolBar'],
  } as AMapLoaderConfig).then((AMap) => {
    cachedAmap = AMap
    return AMap
  })
}

interface AMapLoaderConfig {
  key: string
  securityJsCode?: string
  version: string
  plugins?: string[]
}