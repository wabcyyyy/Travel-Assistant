/**
 * OKLCH → sRGB 十六进制。
 *
 * 用途：MapLibre 的 paint 表达式只能吃具体色值（不能解析 CSS 变量/oklch），
 * day-tint 的每日路线色需要在 JS 侧换算成 hex；系数为标准 OKLab 矩阵
 * （Björn Ottosson），L∈[0,1]，C 为色度，hDeg 为色相角。
 */
export function oklchToHex(l: number, c: number, hDeg: number): string {
  const hRad = (hDeg * Math.PI) / 180
  const a = c * Math.cos(hRad)
  const b = c * Math.sin(hRad)

  // OKLab → 圆锥 LMS
  const lCone = l + 0.3963377774 * a + 0.2158037573 * b
  const mCone = l - 0.1055613458 * a - 0.0638541728 * b
  const sCone = l - 0.0894841775 * a - 1.291485548 * b

  const l3 = lCone ** 3
  const m3 = mCone ** 3
  const s3 = sCone ** 3

  // 圆锥 LMS → 线性 sRGB
  const rLin = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3
  const gLin = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3
  const bLin = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3

  const toByte = (x: number): number => {
    const v = x <= 0.0031308 ? 12.92 * x : 1.055 * Math.max(x, 0) ** (1 / 2.4) - 0.055
    return Math.round(Math.min(Math.max(v, 0), 1) * 255)
  }
  const hex = (n: number): string => n.toString(16).padStart(2, '0')
  return `#${hex(toByte(rLin))}${hex(toByte(gLin))}${hex(toByte(bLin))}`
}
