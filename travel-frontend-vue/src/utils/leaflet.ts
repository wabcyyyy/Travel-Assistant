// Leaflet 免 key 地图加载器（国外目的地 OSM 瓦片，动态注入 CDN）。

let cachedLeaflet: any = null

export function loadLeaflet(): Promise<any> {
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
      cachedLeaflet = (window as any).L
      resolve(cachedLeaflet)
    }
    script.onerror = () => reject(new Error('Leaflet 加载失败（CDN 不可达）'))
    document.head.appendChild(script)
  })
}
