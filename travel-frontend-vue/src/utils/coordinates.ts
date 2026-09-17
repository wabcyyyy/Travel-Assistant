// 高德 URI 接收 GCJ-02；OTM/Nominatim 的 WGS84 仅在打开国内路线时转换。
export function toGcj02(latitude: number, longitude: number): [number, number] {
  if (longitude < 72.004 || longitude > 137.8347 || latitude < 0.8293 || latitude > 55.8271) {
    return [latitude, longitude]
  }
  const x = longitude - 105
  const y = latitude - 35
  const pi = Math.PI
  const wave = (v: number, a: number, b: number) => (a * Math.sin(v * pi) + b * Math.sin(v / 3 * pi)) * 2 / 3
  const common = (20 * Math.sin(6 * x * pi) + 20 * Math.sin(2 * x * pi)) * 2 / 3
  let latOffset = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  latOffset += common + wave(y, 20, 40) + (160 * Math.sin(y / 12 * pi) + 320 * Math.sin(y * pi / 30)) * 2 / 3
  let lonOffset = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  lonOffset += common + wave(x, 20, 40) + (150 * Math.sin(x / 12 * pi) + 300 * Math.sin(x / 30 * pi)) * 2 / 3
  const rad = latitude / 180 * pi
  const magic = 1 - 0.00669342162296594323 * Math.sin(rad) ** 2
  const sqrt = Math.sqrt(magic)
  latOffset = latOffset * 180 / ((6378245 * (1 - 0.00669342162296594323)) / (magic * sqrt) * pi)
  lonOffset = lonOffset * 180 / (6378245 / sqrt * Math.cos(rad) * pi)
  return [latitude + latOffset, longitude + lonOffset]
}
