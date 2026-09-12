// Leaflet 免 key 地图加载器（国外目的地 OSM 瓦片，动态注入 CDN）。

/** Leaflet 全局对象最小接口：仅声明本项目实际调用的成员，不做全量类型化。 */
interface LeafletMapLike {
  fitBounds(bounds: unknown): void
  remove(): void
}

interface LeafletLayerLike {
  addTo(map: LeafletMapLike): LeafletLayerLike
  remove(): void
}

interface LeafletMarkerLike {
  bindPopup(html: string): LeafletMarkerLike
  openPopup(): LeafletMarkerLike
  addTo(map: LeafletMapLike): LeafletMarkerLike
  on(type: string, handler: () => void): LeafletMarkerLike
  remove(): void
}

interface LeafletGlobalLike {
  map(container: HTMLElement, options: { center: [number, number]; zoom: number }): LeafletMapLike
  tileLayer(
    url: string,
    options?: { attribution?: string; maxZoom?: number },
  ): LeafletLayerLike
  divIcon(options?: {
    html?: string
    className?: string
    iconSize?: [number, number]
    iconAnchor?: [number, number]
  }): unknown
  marker(
    latLng: [number, number],
    options?: { icon?: unknown; title?: string },
  ): LeafletMarkerLike
  polyline(
    latLngs: [number, number][],
    options?: { color?: string; weight?: number; opacity?: number },
  ): LeafletLayerLike
  latLngBounds(points: [number, number][]): unknown
}

declare global {
  interface Window {
    L?: LeafletGlobalLike
  }
}

let cachedLeaflet: LeafletGlobalLike | null = null

export function loadLeaflet(): Promise<LeafletGlobalLike> {
  if (cachedLeaflet) return Promise.resolve(cachedLeaflet)
  return new Promise((resolve, reject) => {
    if (!document.querySelector('link[href*="leaflet@1.9.4/dist/leaflet.css"]')) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
      document.head.appendChild(link)
    }
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
    script.async = true
    script.onload = () => {
      cachedLeaflet = window.L ?? null
      if (!cachedLeaflet) {
        reject(new Error('Leaflet 加载失败（window.L 缺失）'))
        return
      }
      resolve(cachedLeaflet)
    }
    script.onerror = () => reject(new Error('Leaflet 加载失败（CDN 不可达）'))
    document.head.appendChild(script)
  })
}
