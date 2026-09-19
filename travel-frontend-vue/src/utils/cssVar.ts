/**
 * 从 CSS 自定义属性令牌取值（外观令牌单一真源，R5-4）。
 *
 * canvas 绘制、内联 style、地图 paint 等「JS 侧取色」一律走这里读 `--lp-*` 令牌，
 * 不再散落裸 hex（theme-lint 已扩扫本文件的调用方）。`fallback` 仅在令牌缺失（如离线、
 * 未加载 theme.css）时兜底，可传十六进制值；调用方若传裸 hex 只允许出现在 `cssVar(...)` 实参内。
 */
export function cssVar(name: string, fallback = ''): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}
